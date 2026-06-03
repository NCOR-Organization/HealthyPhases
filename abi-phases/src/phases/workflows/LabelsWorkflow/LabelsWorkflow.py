"""Labels extraction workflow.

Purpose
- Read existing document chunks from the triple store.
- Restrict processing to solitude/paid papers by source path.
- Ask an LLM to extract concise topical labels from each chunk.
- Persist extracted labels as RDF instances linked to source chunks.

What this workflow expects
- `phases-doc:Chunk` data already exists in the triple store.
- The labels ontology (`labels.ttl`) is available so `ExtractedLabel` can be stored.

Main behavior
- Select candidate chunks, optionally filtered by source paths.
- Always keep only chunks whose `path` contains one of the allowed tokens.
- Skip chunks already processed unless `force=True`.
- Use a constrained prompt and expect strict JSON output:
  `{"labels": ["..."]}`.
- Normalize/deduplicate returned labels and persist them with provenance metadata.

How to run (ABI CLI)
- From the `abi/` directory:
  `uv run abi run script abi_phases/phases/workflows/LabelsWorkflow/LabelsWorkflow.py`
- With options:
  `uv run abi run script abi_phases/phases/workflows/LabelsWorkflow/LabelsWorkflow.py --chunk-limit 50 --force --workers 4`
- Filter to specific paper paths (repeat `--path`):
  `uv run abi run script abi_phases/phases/workflows/LabelsWorkflow/LabelsWorkflow.py --path ".../paper1.pdf" --path ".../paper2.pdf"`
- Dry run audit (first chunk only, no writes):
  `uv run abi run script abi_phases/phases/workflows/LabelsWorkflow/LabelsWorkflow.py --dry-run`
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from typing import cast

import rdflib
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
from rdflib.term import Node

from phases import ABIModule
from phases.ontologies.labels import ExtractedLabel

try:
    from tqdm import tqdm
except Exception:
    tqdm = None


class LabelsWorkflowConfiguration(WorkflowConfiguration):
    model_name: str = "gpt-5-mini"
    prompt_version: str = "v1"
    min_labels_per_chunk: int = 3
    max_labels_per_chunk: int = 8
    max_words_per_label: int = 4
    default_chunk_limit: int | None = None
    model_timeout_seconds: int = 60
    model_max_retries: int = 1
    extraction_workers: int = 10
    allowed_path_tokens: list[str] = ["solitude", "paid"]


class LabelsWorkflowParameters(WorkflowParameters):
    paths: list[str] | None = None
    chunk_limit: int | None = None
    force: bool = False
    workers: int | None = None
    dry_run: bool = False
    show_dry_run_triples: bool = True


class LabelsWorkflow(Workflow[LabelsWorkflowParameters]):
    module: ABIModule
    _configuration: LabelsWorkflowConfiguration

    def __init__(self, configuration: LabelsWorkflowConfiguration):
        super().__init__(configuration)
        self._configuration = configuration
        self.module = ABIModule.get_instance()
        self._chat_model = ChatOpenAI(
            model=configuration.model_name,
            temperature=0,
            timeout=configuration.model_timeout_seconds,
            max_retries=configuration.model_max_retries,
        )

    def _allowed_path_filter(self) -> str:
        tokens = [
            token.strip().lower() for token in self._configuration.allowed_path_tokens
        ]
        tokens = [token for token in tokens if token]
        if not tokens:
            return ""

        filters = [f'CONTAINS(LCASE(STR(?path)), "{token}")' for token in tokens]
        return "FILTER(" + " || ".join(filters) + ")"

    def _build_candidates_query(self, parameters: LabelsWorkflowParameters) -> str:
        path_clause = ""
        if parameters.paths:
            values = " ".join(rdflib.Literal(path).n3() for path in parameters.paths)
            path_clause = f"VALUES ?path {{ {values} }}"

        allowed_path_clause = self._allowed_path_filter()

        dedupe_clause = ""
        if not parameters.force and not parameters.dry_run:
            dedupe_clause = """
            FILTER NOT EXISTS {
                ?existing_label a phases-label:ExtractedLabel ;
                    phases-label:label_from_chunk ?chunk .
            }
            """

        limit = parameters.chunk_limit
        if limit is None:
            limit = self._configuration.default_chunk_limit
        limit_clause = f"LIMIT {limit}" if limit is not None else ""

        return f"""PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>
PREFIX phases-label: <http://purl.obolibrary.org/obo/phases/labels.owl#>

SELECT ?chunk ?chunk_id ?text ?path WHERE {{
    ?chunk a phases-doc:Chunk ;
        phases-doc:chunk_id ?chunk_id ;
        phases-doc:text ?text ;
        phases-doc:chunk_of ?pdf_paper_file .
    ?pdf_paper_file phases-doc:path ?path .
    {path_clause}
    {allowed_path_clause}
    {dedupe_clause}
}}
ORDER BY ?chunk_id
{limit_clause}"""

    def _load_candidate_chunks(
        self, parameters: LabelsWorkflowParameters
    ) -> list[tuple[Node, str, str, str]]:
        rows = self.module.engine.services.triple_store.query(
            self._build_candidates_query(parameters)
        )
        parsed_rows: list[tuple[Node, str, str, str]] = []
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
            parsed_rows.append((cast(Node, chunk), str(chunk_id), str(text), str(path)))

        return parsed_rows

    def _build_prompt(self, chunk_text: str) -> str:
        return f"""Extract topical labels from this text.

Requirements:
- Output {self._configuration.min_labels_per_chunk}-{self._configuration.max_labels_per_chunk} labels.
- Each label must be a short noun phrase ({self._configuration.max_words_per_label} words max).
- Focus on concepts explicitly present in the text.
- Avoid generic labels like "study", "paper", "result", "method".
- Do not duplicate labels.

Return strict JSON only in this format:
{{"labels": ["..."]}}

Text:
{chunk_text}
"""

    def _parse_labels(self, response_text: str) -> list[str]:
        payload: dict[str, list[str]] | None = None

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

        labels = payload.get("labels", []) if payload else []

        if not isinstance(labels, list):
            return []

        cleaned: list[str] = []
        seen: set[str] = set()
        for label in labels:
            if not isinstance(label, str):
                continue
            value = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", label.strip())
            value = re.sub(r"\s+", " ", value)
            value = re.sub(r"[.,;:!?]+$", "", value)
            value = value.lower().strip()
            if not value:
                continue
            if len(value.split()) > self._configuration.max_words_per_label:
                continue
            if value in seen:
                continue
            seen.add(value)
            cleaned.append(value)

        return cleaned[: self._configuration.max_labels_per_chunk]

    def _extract_labels(self, chunk_text: str) -> list[str]:
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

        return self._parse_labels(response_text)

    def _extract_for_chunk(
        self, chunk: tuple[Node, str, str, str]
    ) -> tuple[Node, str, str, str, list[str], str | None]:
        chunk_uri, chunk_id, text, path = chunk
        try:
            labels = self._extract_labels(text)
            return chunk_uri, chunk_id, text, path, labels, None
        except Exception as exc:
            return chunk_uri, chunk_id, text, path, [], str(exc)

    def _persist_labels(self, chunk_uri: Node, chunk_id: str, labels: list[str]) -> int:
        graph = self._build_labels_graph(
            chunk_uri=chunk_uri, chunk_id=chunk_id, labels=labels
        )
        if len(graph) > 0:
            self.module.engine.services.triple_store.insert(graph)

        return len(labels)

    def _build_labels_graph(
        self, chunk_uri: Node, chunk_id: str, labels: list[str]
    ) -> rdflib.Graph:
        graph = rdflib.Graph()
        for index, label_text in enumerate(labels):
            label_hash = hashlib.sha256(f"{chunk_id}:{label_text}".encode()).hexdigest()

            entity = ExtractedLabel(
                label_id=str(uuid.uuid4()),
                label_text=label_text,
                label_hash=label_hash,
                label_number=index,
                source_chunk_id=chunk_id,
                generated_by_model=self._configuration.model_name,
                prompt_version=self._configuration.prompt_version,
                creation_time=datetime.datetime.now(datetime.UTC),
                label_from_chunk=str(chunk_uri),
            )
            graph += entity.rdf()

        return graph

    def run(self, parameters: LabelsWorkflowParameters):
        logger.debug("Running labels workflow")
        if parameters.dry_run:
            print("[LabelsWorkflow][dry-run] Loading candidate chunks...", flush=True)
        chunks = self._load_candidate_chunks(parameters)
        logger.debug(f"Labels workflow candidate chunks: {len(chunks)}")
        if parameters.dry_run:
            print(
                f"[LabelsWorkflow][dry-run] Candidate chunks: {len(chunks)}",
                flush=True,
            )

        if parameters.dry_run and len(chunks) == 0:
            print("[LabelsWorkflow][dry-run] No candidate chunks found.", flush=True)
            return

        if parameters.dry_run:
            chunk_uri, chunk_id, text, path = chunks[0]
            print(
                "[LabelsWorkflow][dry-run] Calling model "
                f"{self._configuration.model_name} (timeout="
                f"{self._configuration.model_timeout_seconds}s)...",
                flush=True,
            )

            _, _, _, _, labels, error = self._extract_for_chunk(chunks[0])
            try:
                if error is not None:
                    raise RuntimeError(error)
                print(
                    f"[LabelsWorkflow][dry-run] Model returned {len(labels)} parsed labels.",
                    flush=True,
                )
            except Exception as exc:
                logger.error(
                    f"Failed to extract labels for chunk {chunk_id} ({path}): {exc}"
                )
                print(f"[LabelsWorkflow][dry-run] Model call failed: {exc}", flush=True)
                return

            if len(labels) < self._configuration.min_labels_per_chunk:
                logger.warning(
                    f"Chunk {chunk_id} produced {len(labels)} labels; expected at least "
                    f"{self._configuration.min_labels_per_chunk}"
                )

            logger.info("Labels workflow dry run audit")
            logger.info(f"Chunk ID: {chunk_id}")
            logger.info(f"Source path: {path}")
            logger.info("Input chunk text:")
            logger.info(text)
            logger.info("Generated labels:")
            for index, label in enumerate(labels, start=1):
                logger.info(f"{index}. {label}")
            logger.info("Dry run enabled: no labels persisted.")

            print("[LabelsWorkflow][dry-run] Audit", flush=True)
            print(f"Chunk ID: {chunk_id}", flush=True)
            print(f"Source path: {path}", flush=True)
            print("\nInput chunk text:\n", flush=True)
            print(text, flush=True)
            print("\nGenerated labels:\n", flush=True)
            if len(labels) == 0:
                print("(no labels parsed from model output)", flush=True)
            else:
                for index, label in enumerate(labels, start=1):
                    print(f"{index}. {label}", flush=True)

            if parameters.show_dry_run_triples:
                dry_run_graph = self._build_labels_graph(
                    chunk_uri=chunk_uri,
                    chunk_id=chunk_id,
                    labels=labels,
                )
                print("\nTriples that would be inserted (Turtle):\n", flush=True)
                print(dry_run_graph.serialize(format="turtle"), flush=True)
            print("\nDry run enabled: no labels persisted.", flush=True)
            return

        workers = parameters.workers
        if workers is None:
            workers = self._configuration.extraction_workers
        workers = max(1, workers)

        extracted_count = 0
        if workers > 1:
            logger.debug(f"Labels workflow parallel workers: {workers}")
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(self._extract_for_chunk, chunk) for chunk in chunks
                ]
                completion_iter = as_completed(futures)
                if tqdm is not None:
                    completion_iter = tqdm(
                        completion_iter,
                        total=len(futures),
                        desc="Extracting labels",
                        unit="chunk",
                    )
                results = [future.result() for future in completion_iter]
        else:
            chunk_iter = chunks
            if tqdm is not None:
                chunk_iter = tqdm(chunks, desc="Extracting labels", unit="chunk")
            results = [self._extract_for_chunk(chunk) for chunk in chunk_iter]

        results_iter = results
        if tqdm is not None:
            results_iter = tqdm(results, desc="Persisting labels", unit="chunk")

        for chunk_uri, chunk_id, text, path, labels, error in results_iter:
            if error is not None:
                logger.error(
                    f"Failed to extract labels for chunk {chunk_id} ({path}): {error}"
                )
                continue

            if len(labels) < self._configuration.min_labels_per_chunk:
                logger.warning(
                    f"Chunk {chunk_id} produced {len(labels)} labels; expected at least "
                    f"{self._configuration.min_labels_per_chunk}"
                )

            extracted_count += self._persist_labels(chunk_uri, chunk_id, labels)

        logger.debug(f"Labels workflow completed; extracted labels: {extracted_count}")

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

    parser = argparse.ArgumentParser(description="Extract labels from existing chunks")
    parser.add_argument(
        "--path",
        dest="paths",
        action="append",
        default=None,
        help="Paper path to include (can be provided multiple times)",
    )
    parser.add_argument(
        "--chunk-limit",
        type=int,
        default=None,
        help="Maximum number of chunks to process",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess chunks even if labels already exist",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel LLM workers for non-dry runs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Audit mode: process only first chunk, print input and generated labels, "
            "do not persist"
        ),
    )
    parser.add_argument(
        "--no-dry-run-triples",
        action="store_true",
        help="In dry-run mode, disable printing of RDF triples preview",
    )

    args = parser.parse_args()

    workflow = LabelsWorkflow(LabelsWorkflowConfiguration())
    workflow.run(
        LabelsWorkflowParameters(
            paths=args.paths,
            chunk_limit=args.chunk_limit,
            force=args.force,
            workers=args.workers,
            dry_run=args.dry_run,
            show_dry_run_triples=not args.no_dry_run_triples,
        )
    )
