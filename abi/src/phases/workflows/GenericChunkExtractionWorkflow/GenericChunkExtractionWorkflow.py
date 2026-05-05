"""Generic chunk extraction workflow.

Purpose
- Read existing document chunks from the triple store.
- Run a configurable prompt against each chunk with an LLM.
- Return a mapping {chunk_id: [extracted_items]} and optionally write it to a
  JSON file.

Prompt contract
- The `prompt_template` must contain the placeholder `{chunk_text}`.
- The model must respond in strict JSON of the form:
  `{"<output_key>": ["...", "..."]}`
- `output_key` is configurable (defaults to "results").

How to run (ABI CLI)
- From the `abi/` directory:
  `uv run abi run script abi_phases/phases/workflows/GenericChunkExtractionWorkflow/GenericChunkExtractionWorkflow.py \
        --prompt-file ./prompt.txt --output ./out.json`
"""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import cast

from fastapi import APIRouter
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from naas_abi_core import logger
from naas_abi_core.workflow.workflow import (
    Workflow,
    WorkflowConfiguration,
    WorkflowParameters,
)
import rdflib
from rdflib.term import Node

from phases import ABIModule

try:
    from tqdm import tqdm
except Exception:
    tqdm = None


@dataclass
class GenericChunkExtractionWorkflowConfiguration(WorkflowConfiguration):
    prompt_template: str = (
        "Extract key information from this text.\n\n"
        'Return strict JSON only in this format: {{"results": ["..."]}}\n\n'
        "Text:\n{chunk_text}\n"
    )
    output_key: str = "results"
    model_name: str = "gpt-5-mini"
    model_timeout_seconds: int = 60
    model_max_retries: int = 1
    extraction_workers: int = 10
    max_items_per_chunk: int | None = None
    pipeline_name: str = "default"


PHASES_DOC = rdflib.Namespace("http://purl.obolibrary.org/obo/phases/documents.owl#")
PAPERS_GRAPH = rdflib.URIRef("http://ontology.naas.ai/graph/phases/papers")
EXTRACTIONS_GRAPH = rdflib.URIRef(
    "http://ontology.naas.ai/graph/phases/extractions"
)


class GenericChunkExtractionWorkflowParameters(WorkflowParameters):
    paths: list[str] | None = None
    chunk_limit: int | None = None
    workers: int | None = None
    output_path: str | None = None
    dry_run: bool = False


class GenericChunkExtractionWorkflow(
    Workflow[GenericChunkExtractionWorkflowParameters]
):
    module: ABIModule
    _configuration: GenericChunkExtractionWorkflowConfiguration

    def __init__(self, configuration: GenericChunkExtractionWorkflowConfiguration):
        super().__init__(configuration)
        self._configuration = configuration
        self.module = ABIModule.get_instance()
        if "{chunk_text}" not in configuration.prompt_template:
            raise ValueError(
                "prompt_template must contain the '{chunk_text}' placeholder"
            )
        self._chat_model = ChatOpenAI(
            model=configuration.model_name,
            temperature=0,
            timeout=configuration.model_timeout_seconds,
            max_retries=configuration.model_max_retries,
        )

    def _extraction_id(self) -> tuple[str, str, rdflib.URIRef]:
        """Returns (extraction_id, prompt_hash, extraction_uri)."""
        cfg = self._configuration
        prompt_hash = hashlib.sha256(cfg.prompt_template.encode()).hexdigest()
        extraction_id = f"{cfg.model_name}:{cfg.pipeline_name}:{prompt_hash[:16]}"
        return (
            extraction_id,
            prompt_hash,
            rdflib.URIRef(f"urn:phases:extraction:{extraction_id}"),
        )

    def _build_candidates_query(
        self, parameters: GenericChunkExtractionWorkflowParameters
    ) -> str:
        path_clause = ""
        if parameters.paths:
            values = " ".join(rdflib.Literal(path).n3() for path in parameters.paths)
            path_clause = f"VALUES ?path {{ {values} }}"

        limit = parameters.chunk_limit
        limit_clause = f"LIMIT {limit}" if limit is not None else ""

        _, _, extraction_uri = self._extraction_id()

        return f"""PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>

SELECT ?chunk ?chunk_id ?text ?path WHERE {{
    GRAPH <{PAPERS_GRAPH}> {{
        ?chunk a phases-doc:Chunk ;
            phases-doc:chunk_id ?chunk_id ;
            phases-doc:text ?text ;
            phases-doc:chunk_of ?pdf_paper_file .
        ?pdf_paper_file phases-doc:path ?path .
        {path_clause}
    }}
    # Skip chunks already processed by this Extraction (same prompt + model + pipeline).
    FILTER NOT EXISTS {{
        GRAPH <{EXTRACTIONS_GRAPH}> {{
            ?already_done a phases-doc:ExtractedItem ;
                phases-doc:extracted_by <{extraction_uri}> ;
                phases-doc:extracted_from_chunk ?chunk .
        }}
    }}
}}
ORDER BY ?chunk_id
{limit_clause}"""

    def _load_candidate_chunks(
        self, parameters: GenericChunkExtractionWorkflowParameters
    ) -> list[tuple[Node, str, str, str]]:
        rows = self.module.engine.services.triple_store.query(
            self._build_candidates_query(parameters)
        )
        parsed: list[tuple[Node, str, str, str]] = []
        for row in rows:
            if isinstance(row, bool):
                continue
            try:
                items = tuple(row)
            except TypeError:
                continue
            if len(items) != 4:
                continue
            chunk, chunk_id, text, path = items
            parsed.append((cast(Node, chunk), str(chunk_id), str(text), str(path)))
        return parsed

    def _build_prompt(self, chunk_text: str) -> str:
        return self._configuration.prompt_template.format(chunk_text=chunk_text)

    def _parse_response(self, response_text: str) -> list[str]:
        payload: dict | None = None
        try:
            parsed = json.loads(response_text)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", response_text, flags=re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict):
                        payload = parsed
                except json.JSONDecodeError:
                    payload = None

        items = payload.get(self._configuration.output_key, []) if payload else []
        if not isinstance(items, list):
            return []

        cleaned: list[str] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, str):
                continue
            value = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", item.strip())
            value = re.sub(r"\s+", " ", value)
            if not value or value in seen:
                continue
            seen.add(value)
            cleaned.append(value)

        if self._configuration.max_items_per_chunk is not None:
            cleaned = cleaned[: self._configuration.max_items_per_chunk]
        return cleaned

    def _extract(self, chunk_text: str) -> list[str]:
        prompt = self._build_prompt(chunk_text)
        response: AIMessage = cast(AIMessage, self._chat_model.invoke(prompt))
        content = response.content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            response_text = "\n".join(parts)
        else:
            response_text = str(content)
        return self._parse_response(response_text)

    def _extract_for_chunk(
        self, chunk: tuple[Node, str, str, str]
    ) -> tuple[str, str, list[str], str | None]:
        _, chunk_id, text, path = chunk
        try:
            return chunk_id, path, self._extract(text), None
        except Exception as exc:
            return chunk_id, path, [], str(exc)

    def run(
        self, parameters: GenericChunkExtractionWorkflowParameters
    ) -> dict[str, list[str]]:
        chunks = self._load_candidate_chunks(parameters)
        logger.debug(f"Generic extraction candidate chunks: {len(chunks)}")

        if parameters.dry_run:
            if not chunks:
                print("[GenericChunkExtraction][dry-run] No candidate chunks.", flush=True)
                return {}
            chunk_id, path, items, error = self._extract_for_chunk(chunks[0])
            print(f"[dry-run] Chunk ID: {chunk_id}", flush=True)
            print(f"[dry-run] Source path: {path}", flush=True)
            if error:
                print(f"[dry-run] Error: {error}", flush=True)
            else:
                print(f"[dry-run] {len(items)} items extracted:", flush=True)
                for i, it in enumerate(items, 1):
                    print(f"  {i}. {it}", flush=True)
            return {chunk_id: items}

        workers = parameters.workers or self._configuration.extraction_workers
        workers = max(1, workers)

        results: dict[str, list[str]] = {}
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(self._extract_for_chunk, c) for c in chunks
                ]
                completion = as_completed(futures)
                if tqdm is not None:
                    completion = tqdm(
                        completion, total=len(futures), desc="Extracting", unit="chunk"
                    )
                for future in completion:
                    chunk_id, path, items, error = future.result()
                    if error:
                        logger.error(f"Chunk {chunk_id} ({path}) failed: {error}")
                        continue
                    results[chunk_id] = items
        else:
            chunk_iter = chunks
            if tqdm is not None:
                chunk_iter = tqdm(chunks, desc="Extracting", unit="chunk")
            for chunk in chunk_iter:
                chunk_id, path, items, error = self._extract_for_chunk(chunk)
                if error:
                    logger.error(f"Chunk {chunk_id} ({path}) failed: {error}")
                    continue
                results[chunk_id] = items

        if parameters.output_path:
            Path(parameters.output_path).write_text(json.dumps(results, indent=2))
            logger.debug(f"Wrote results to {parameters.output_path}")

        self._persist_to_triple_store(results)
        return results

    def _persist_to_triple_store(self, results: dict[str, list[str]]) -> None:
        if not results:
            return

        cfg = self._configuration
        extraction_id, prompt_hash, extraction_uri = self._extraction_id()

        graph = rdflib.Graph()
        graph.add((extraction_uri, rdflib.RDF.type, PHASES_DOC.Extraction))
        graph.add(
            (extraction_uri, PHASES_DOC.extraction_id, rdflib.Literal(extraction_id))
        )
        graph.add(
            (
                extraction_uri,
                PHASES_DOC.pipeline_name,
                rdflib.Literal(cfg.pipeline_name),
            )
        )
        graph.add(
            (extraction_uri, PHASES_DOC.output_key, rdflib.Literal(cfg.output_key))
        )
        graph.add(
            (
                extraction_uri,
                PHASES_DOC.prompt_template,
                rdflib.Literal(cfg.prompt_template),
            )
        )
        graph.add(
            (extraction_uri, PHASES_DOC.prompt_hash, rdflib.Literal(prompt_hash))
        )
        graph.add(
            (extraction_uri, PHASES_DOC.model_name, rdflib.Literal(cfg.model_name))
        )

        chunk_uri_by_id = self._resolve_chunk_uris(list(results.keys()))

        for chunk_id, items in results.items():
            chunk_uri = chunk_uri_by_id.get(chunk_id)
            if chunk_uri is None:
                logger.warning(
                    f"No Chunk URI found for chunk_id {chunk_id}; skipping its extracted items."
                )
                continue
            for i, text in enumerate(items):
                item_id = hashlib.sha256(
                    f"{extraction_id}:{chunk_id}:{i}:{text}".encode()
                ).hexdigest()
                item_uri = rdflib.URIRef(f"urn:phases:extracted_item:{item_id}")
                graph.add((item_uri, rdflib.RDF.type, PHASES_DOC.ExtractedItem))
                graph.add(
                    (item_uri, PHASES_DOC.extracted_item_id, rdflib.Literal(item_id))
                )
                graph.add(
                    (item_uri, PHASES_DOC.extracted_text, rdflib.Literal(text))
                )
                graph.add((item_uri, PHASES_DOC.item_number, rdflib.Literal(i)))
                graph.add((item_uri, PHASES_DOC.extracted_by, extraction_uri))
                graph.add((item_uri, PHASES_DOC.extracted_from_chunk, chunk_uri))

        logger.debug(
            f"Inserting extraction graph: 1 Extraction + "
            f"{sum(len(v) for v in results.values())} ExtractedItem(s)"
        )
        self.module.engine.services.triple_store.insert(
            graph, graph_name=EXTRACTIONS_GRAPH
        )

    def _resolve_chunk_uris(self, chunk_ids: list[str]) -> dict[str, rdflib.URIRef]:
        if not chunk_ids:
            return {}
        values = " ".join(rdflib.Literal(cid).n3() for cid in chunk_ids)
        query = f"""PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>
SELECT ?chunk ?chunk_id WHERE {{
    GRAPH <{PAPERS_GRAPH}> {{
        ?chunk a phases-doc:Chunk ; phases-doc:chunk_id ?chunk_id .
        VALUES ?chunk_id {{ {values} }}
    }}
}}"""
        rows = self.module.engine.services.triple_store.query(query)
        return {str(chunk_id): cast(rdflib.URIRef, chunk) for chunk, chunk_id in rows}

    def as_tools(self) -> list[BaseTool]:
        return []

    def as_api(
        self,
        router: APIRouter,
        route_name: str = "",
        name: str = "",
        description: str = "",
        description_stream: str = "",
        tags: list[str | Enum] | None = [],
    ) -> None:
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run a generic LLM extraction over document chunks"
    )
    parser.add_argument(
        "--prompt-file",
        type=str,
        default=None,
        help="Path to a text file containing the prompt template (must include {chunk_text})",
    )
    parser.add_argument(
        "--output-key",
        type=str,
        default="results",
        help='JSON key expected in the model response (default: "results")',
    )
    parser.add_argument("--model", type=str, default="gpt-5-mini")
    parser.add_argument(
        "--path",
        dest="paths",
        action="append",
        default=None,
        help="Paper path to include (repeatable)",
    )
    parser.add_argument("--chunk-limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to write the {chunk_id: [items]} JSON result",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config_kwargs: dict = {"model_name": args.model, "output_key": args.output_key}
    if args.prompt_file:
        config_kwargs["prompt_template"] = Path(args.prompt_file).read_text()

    workflow = GenericChunkExtractionWorkflow(
        GenericChunkExtractionWorkflowConfiguration(**config_kwargs)
    )
    workflow.run(
        GenericChunkExtractionWorkflowParameters(
            paths=args.paths,
            chunk_limit=args.chunk_limit,
            workers=args.workers,
            output_path=args.output,
            dry_run=args.dry_run,
        )
    )
