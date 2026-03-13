"""Axioms extraction workflow.

Purpose
- Read existing document chunks from the triple store.
- Ask an LLM to extract general, natural-language axioms from each chunk.
- Persist extracted axioms as RDF instances linked to source chunks.

What this workflow expects
- `phases-doc:Chunk` data already exists in the triple store (typically created by
  PapersIngestionWorkflow).
- The axioms ontology (`axioms.ttl`) is available so `ExtractedAxiom` can be stored.

Main behavior
- Select candidate chunks, optionally filtered by source paths.
- Skip chunks already processed unless `force=True`.
- Use a constrained prompt and expect strict JSON output:
  `{"axioms": ["..."]}`.
- Normalize/deduplicate returned axioms and persist them with provenance metadata.

Key parameters
- `paths`: limit processing to chunks from selected paper paths.
- `chunk_limit`: limit number of chunks processed in one run.
- `force`: reprocess chunks even if extracted axioms already exist.
- `workers`: number of parallel LLM workers for non-dry runs.
- `dry_run`: process only the first candidate chunk, print audit details, and
  skip persistence.
- `show_dry_run_triples`: when `dry_run` is enabled, print the RDF triples that
  would be inserted.

Persistence model
- Each extracted axiom is stored as `phases-ax:ExtractedAxiom` and linked to a
  source `phases-doc:Chunk` through `phases-ax:axiom_from_chunk`.

How to run (ABI CLI)
- From the `abi/` directory:
  `uv run abi run script abi_phases/phases/workflows/AxiomsWorkflow/AxiomsWorkflow.py`
- With options:
  `uv run abi run script abi_phases/phases/workflows/AxiomsWorkflow/AxiomsWorkflow.py --chunk-limit 50 --force --workers 4`
- Filter to specific paper paths (repeat `--path`):
  `uv run abi run script abi_phases/phases/workflows/AxiomsWorkflow/AxiomsWorkflow.py --path ".../paper1.pdf" --path ".../paper2.pdf"`
- Dry run audit (first chunk only, no writes):
  `uv run abi run script abi_phases/phases/workflows/AxiomsWorkflow/AxiomsWorkflow.py --dry-run`
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
from phases.ontologies.axioms import ExtractedAxiom

try:
    from tqdm import tqdm
except Exception:
    tqdm = None


class AxiomsWorkflowConfiguration(WorkflowConfiguration):
    model_name: str = "gpt-5-mini"
    prompt_version: str = "v1"
    min_axioms_per_chunk: int = 5
    max_axioms_per_chunk: int = 10
    default_chunk_limit: int | None = None
    model_timeout_seconds: int = 60
    model_max_retries: int = 1
    extraction_workers: int = 10


class AxiomsWorkflowParameters(WorkflowParameters):
    paths: list[str] | None = None
    chunk_limit: int | None = None
    force: bool = False
    workers: int | None = None
    dry_run: bool = False
    show_dry_run_triples: bool = True


class AxiomsWorkflow(Workflow[AxiomsWorkflowParameters]):
    module: ABIModule
    _configuration: AxiomsWorkflowConfiguration

    def __init__(self, configuration: AxiomsWorkflowConfiguration):
        super().__init__(configuration)
        self._configuration = configuration
        self.module = ABIModule.get_instance()
        self._chat_model = ChatOpenAI(
            model=configuration.model_name,
            temperature=0,
            timeout=configuration.model_timeout_seconds,
            max_retries=configuration.model_max_retries,
        )

    def _build_candidates_query(self, parameters: AxiomsWorkflowParameters) -> str:
        path_clause = ""
        if parameters.paths:
            values = " ".join(rdflib.Literal(path).n3() for path in parameters.paths)
            path_clause = f"VALUES ?path {{ {values} }}"

        dedupe_clause = ""
        if not parameters.force and not parameters.dry_run:
            dedupe_clause = """
            FILTER NOT EXISTS {
                ?existing_axiom a phases-ax:ExtractedAxiom ;
                    phases-ax:axiom_from_chunk ?chunk .
            }
            """

        limit = parameters.chunk_limit
        if limit is None:
            limit = self._configuration.default_chunk_limit
        limit_clause = f"LIMIT {limit}" if limit is not None else ""

        return f"""PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>
PREFIX phases-ax: <http://purl.obolibrary.org/obo/phases/axioms.owl#>

SELECT ?chunk ?chunk_id ?text ?path WHERE {{
    ?chunk a phases-doc:Chunk ;
        phases-doc:chunk_id ?chunk_id ;
        phases-doc:text ?text ;
        phases-doc:chunk_of ?pdf_paper_file .
    ?pdf_paper_file phases-doc:path ?path .
    {path_clause}
    {dedupe_clause}
}}
ORDER BY ?chunk_id
{limit_clause}"""

    def _load_candidate_chunks(
        self, parameters: AxiomsWorkflowParameters
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
        return f"""Extract the main logical axioms (general rules) from this text.

Requirements:
- Write each axiom as a short general statement.
- Use forms like "If..., then...", "X tends to...", "X occurs only when..."
- Do not copy sentences verbatim.
- Do not add assumptions not stated in the text.
- Output {self._configuration.min_axioms_per_chunk}-{self._configuration.max_axioms_per_chunk} axioms.

Return strict JSON only in this format:
{{"axioms": ["..."]}}

Text:
{chunk_text}
"""

    def _parse_axioms(self, response_text: str) -> list[str]:
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

        axioms = payload.get("axioms", []) if payload else []

        if not isinstance(axioms, list):
            return []

        cleaned: list[str] = []
        seen: set[str] = set()
        for axiom in axioms:
            if not isinstance(axiom, str):
                continue
            value = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", axiom.strip())
            value = re.sub(r"\s+", " ", value)
            if not value:
                continue
            if value in seen:
                continue
            seen.add(value)
            cleaned.append(value)

        return cleaned[: self._configuration.max_axioms_per_chunk]

    def _extract_axioms(self, chunk_text: str) -> list[str]:
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

        return self._parse_axioms(response_text)

    def _extract_for_chunk(
        self, chunk: tuple[Node, str, str, str]
    ) -> tuple[Node, str, str, str, list[str], str | None]:
        chunk_uri, chunk_id, text, path = chunk
        try:
            axioms = self._extract_axioms(text)
            return chunk_uri, chunk_id, text, path, axioms, None
        except Exception as exc:
            return chunk_uri, chunk_id, text, path, [], str(exc)

    def _persist_axioms(self, chunk_uri: Node, chunk_id: str, axioms: list[str]) -> int:
        graph = self._build_axioms_graph(
            chunk_uri=chunk_uri, chunk_id=chunk_id, axioms=axioms
        )
        if len(graph) > 0:
            self.module.engine.services.triple_store.insert(graph)

        return len(axioms)

    def _build_axioms_graph(
        self, chunk_uri: Node, chunk_id: str, axioms: list[str]
    ) -> rdflib.Graph:
        graph = rdflib.Graph()
        for index, axiom_text in enumerate(axioms):
            axiom_hash = hashlib.sha256(f"{chunk_id}:{axiom_text}".encode()).hexdigest()

            entity = ExtractedAxiom(
                axiom_id=str(uuid.uuid4()),
                axiom_text=axiom_text,
                axiom_hash=axiom_hash,
                axiom_number=index,
                source_chunk_id=chunk_id,
                generated_by_model=self._configuration.model_name,
                prompt_version=self._configuration.prompt_version,
                creation_time=datetime.datetime.now(datetime.UTC),
                axiom_from_chunk=str(chunk_uri),
            )
            graph += entity.rdf()

        return graph

    def run(self, parameters: AxiomsWorkflowParameters):
        logger.debug("Running axioms workflow")
        if parameters.dry_run:
            print("[AxiomsWorkflow][dry-run] Loading candidate chunks...", flush=True)
        chunks = self._load_candidate_chunks(parameters)
        logger.debug(f"Axioms workflow candidate chunks: {len(chunks)}")
        if parameters.dry_run:
            print(
                f"[AxiomsWorkflow][dry-run] Candidate chunks: {len(chunks)}",
                flush=True,
            )

        if parameters.dry_run and len(chunks) == 0:
            print("[AxiomsWorkflow][dry-run] No candidate chunks found.", flush=True)
            return

        if parameters.dry_run:
            chunk_uri, chunk_id, text, path = chunks[0]
            print(
                "[AxiomsWorkflow][dry-run] Calling model "
                f"{self._configuration.model_name} (timeout="
                f"{self._configuration.model_timeout_seconds}s)...",
                flush=True,
            )

            _, _, _, _, axioms, error = self._extract_for_chunk(chunks[0])
            try:
                if error is not None:
                    raise RuntimeError(error)
                print(
                    f"[AxiomsWorkflow][dry-run] Model returned {len(axioms)} parsed axioms.",
                    flush=True,
                )
            except Exception as exc:
                logger.error(
                    f"Failed to extract axioms for chunk {chunk_id} ({path}): {exc}"
                )
                print(f"[AxiomsWorkflow][dry-run] Model call failed: {exc}", flush=True)
                return

            if len(axioms) < self._configuration.min_axioms_per_chunk:
                logger.warning(
                    f"Chunk {chunk_id} produced {len(axioms)} axioms; expected at least "
                    f"{self._configuration.min_axioms_per_chunk}"
                )

            logger.info("Axioms workflow dry run audit")
            logger.info(f"Chunk ID: {chunk_id}")
            logger.info(f"Source path: {path}")
            logger.info("Input chunk text:")
            logger.info(text)
            logger.info("Generated axioms:")
            for index, axiom in enumerate(axioms, start=1):
                logger.info(f"{index}. {axiom}")
            logger.info("Dry run enabled: no axioms persisted.")

            print("[AxiomsWorkflow][dry-run] Audit", flush=True)
            print(f"Chunk ID: {chunk_id}", flush=True)
            print(f"Source path: {path}", flush=True)
            print("\nInput chunk text:\n", flush=True)
            print(text, flush=True)
            print("\nGenerated axioms:\n", flush=True)
            if len(axioms) == 0:
                print("(no axioms parsed from model output)", flush=True)
            else:
                for index, axiom in enumerate(axioms, start=1):
                    print(f"{index}. {axiom}", flush=True)

            if parameters.show_dry_run_triples:
                dry_run_graph = self._build_axioms_graph(
                    chunk_uri=chunk_uri,
                    chunk_id=chunk_id,
                    axioms=axioms,
                )
                print("\nTriples that would be inserted (Turtle):\n", flush=True)
                print(dry_run_graph.serialize(format="turtle"), flush=True)
            print("\nDry run enabled: no axioms persisted.", flush=True)
            return

        workers = parameters.workers
        if workers is None:
            workers = self._configuration.extraction_workers
        workers = max(1, workers)

        extracted_count = 0
        if workers > 1:
            logger.debug(f"Axioms workflow parallel workers: {workers}")
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(self._extract_for_chunk, chunk) for chunk in chunks
                ]
                completion_iter = as_completed(futures)
                if tqdm is not None:
                    completion_iter = tqdm(
                        completion_iter,
                        total=len(futures),
                        desc="Extracting axioms",
                        unit="chunk",
                    )
                results = [future.result() for future in completion_iter]
        else:
            chunk_iter = chunks
            if tqdm is not None:
                chunk_iter = tqdm(chunks, desc="Extracting axioms", unit="chunk")
            results = [self._extract_for_chunk(chunk) for chunk in chunk_iter]

        results_iter = results
        if tqdm is not None:
            results_iter = tqdm(results, desc="Persisting axioms", unit="chunk")

        for chunk_uri, chunk_id, text, path, axioms, error in results_iter:
            if error is not None:
                logger.error(
                    f"Failed to extract axioms for chunk {chunk_id} ({path}): {error}"
                )
                continue

            if len(axioms) < self._configuration.min_axioms_per_chunk:
                logger.warning(
                    f"Chunk {chunk_id} produced {len(axioms)} axioms; expected at least "
                    f"{self._configuration.min_axioms_per_chunk}"
                )

            extracted_count += self._persist_axioms(chunk_uri, chunk_id, axioms)

        logger.debug(f"Axioms workflow completed; extracted axioms: {extracted_count}")

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

    parser = argparse.ArgumentParser(description="Extract axioms from existing chunks")
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
        help="Reprocess chunks even if axioms already exist",
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
            "Audit mode: process only first chunk, print input and generated axioms, "
            "do not persist"
        ),
    )
    parser.add_argument(
        "--no-dry-run-triples",
        action="store_true",
        help="In dry-run mode, disable printing of RDF triples preview",
    )

    args = parser.parse_args()

    workflow = AxiomsWorkflow(AxiomsWorkflowConfiguration())
    workflow.run(
        AxiomsWorkflowParameters(
            paths=args.paths,
            chunk_limit=args.chunk_limit,
            force=args.force,
            workers=args.workers,
            dry_run=args.dry_run,
            show_dry_run_triples=not args.no_dry_run_triples,
        )
    )
