"""Analyze similar axioms across different paper paths.

Purpose
- Load extracted axioms from the triple store.
- For each axiom text, run vector similarity search.
- Keep only matches coming from a different paper path.
- Export a CSV to inspect repeated ideas across literature.

How to run (from `abi/`)
- `uv run abi run script abi_phases/phases/workflows/AxiomsCrossPaperSimilarityWorkflow/AxiomsCrossPaperSimilarityWorkflow.py`
- `uv run abi run script abi_phases/phases/workflows/AxiomsCrossPaperSimilarityWorkflow/AxiomsCrossPaperSimilarityWorkflow.py --score-threshold 0.8 --matches-per-axiom 5`
"""

from __future__ import annotations

import csv
import os
import uuid
from enum import Enum
from pathlib import Path
from typing import cast

import numpy as np
import rdflib
from fastapi import APIRouter
from langchain_core.tools import BaseTool
from langchain_openai import OpenAIEmbeddings
from naas_abi_core import logger
from naas_abi_core.services.vector_store.IVectorStorePort import SearchResult
from naas_abi_core.workflow.workflow import (
    Workflow,
    WorkflowConfiguration,
    WorkflowParameters,
)

from abi_phases.phases import ABIModule

try:
    from tqdm import tqdm
except Exception:
    tqdm = None


class AxiomsCrossPaperSimilarityWorkflowConfiguration(WorkflowConfiguration):
    collection_name: str = "phases_axioms"
    embedding_model_name: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072
    search_k: int = 25
    matches_per_axiom: int = 5
    score_threshold: float = 0.75
    default_limit: int | None = None


class AxiomsCrossPaperSimilarityWorkflowParameters(WorkflowParameters):
    output_csv_path: str
    paths: list[str] | None = None
    collection_name: str | None = None
    search_k: int | None = None
    matches_per_axiom: int | None = None
    score_threshold: float | None = None
    limit: int | None = None


class AxiomsCrossPaperSimilarityWorkflow(
    Workflow[AxiomsCrossPaperSimilarityWorkflowParameters]
):
    module: ABIModule
    _configuration: AxiomsCrossPaperSimilarityWorkflowConfiguration

    def __init__(self, configuration: AxiomsCrossPaperSimilarityWorkflowConfiguration):
        super().__init__(configuration)
        self._configuration = configuration
        self.module = ABIModule.get_instance()
        self._embeddings = OpenAIEmbeddings(
            model=configuration.embedding_model_name,
            dimensions=configuration.embedding_dimensions,
        )

    def _effective_collection_name(
        self, parameters: AxiomsCrossPaperSimilarityWorkflowParameters
    ) -> str:
        return parameters.collection_name or self._configuration.collection_name

    def _effective_search_k(
        self, parameters: AxiomsCrossPaperSimilarityWorkflowParameters
    ) -> int:
        value = (
            parameters.search_k
            if parameters.search_k is not None
            else self._configuration.search_k
        )
        return max(1, value)

    def _effective_matches_per_axiom(
        self, parameters: AxiomsCrossPaperSimilarityWorkflowParameters
    ) -> int:
        value = (
            parameters.matches_per_axiom
            if parameters.matches_per_axiom is not None
            else self._configuration.matches_per_axiom
        )
        return max(1, value)

    def _effective_score_threshold(
        self, parameters: AxiomsCrossPaperSimilarityWorkflowParameters
    ) -> float:
        if parameters.score_threshold is not None:
            return parameters.score_threshold
        return self._configuration.score_threshold

    def _effective_limit(
        self, parameters: AxiomsCrossPaperSimilarityWorkflowParameters
    ) -> int | None:
        if parameters.limit is not None:
            return parameters.limit
        return self._configuration.default_limit

    def _build_query(
        self, parameters: AxiomsCrossPaperSimilarityWorkflowParameters
    ) -> str:
        path_clause = ""
        if parameters.paths:
            values = " ".join(rdflib.Literal(path).n3() for path in parameters.paths)
            path_clause = f"VALUES ?path {{ {values} }}"

        limit = self._effective_limit(parameters)
        limit_clause = f"LIMIT {limit}" if limit is not None else ""

        return f"""PREFIX phases-ax: <http://purl.obolibrary.org/obo/phases/axioms.owl#>
PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>

SELECT ?axiom ?axiom_id ?axiom_hash ?axiom_text ?chunk_id ?path WHERE {{
    ?axiom a phases-ax:ExtractedAxiom ;
        phases-ax:axiom_id ?axiom_id ;
        phases-ax:axiom_hash ?axiom_hash ;
        phases-ax:axiom_text ?axiom_text ;
        phases-ax:axiom_from_chunk ?chunk .
    OPTIONAL {{ ?axiom phases-ax:source_chunk_id ?chunk_id . }}
    OPTIONAL {{
        ?chunk phases-doc:chunk_of ?pdf_paper_file .
        ?pdf_paper_file phases-doc:path ?path .
    }}
    {path_clause}
}}
ORDER BY ?axiom_id
{limit_clause}"""

    def _load_axioms(
        self, parameters: AxiomsCrossPaperSimilarityWorkflowParameters
    ) -> list[tuple[str, str, str, str, str, str]]:
        rows = self.module.engine.services.triple_store.query(
            self._build_query(parameters)
        )
        parsed: list[tuple[str, str, str, str, str, str]] = []

        for row in rows:
            if isinstance(row, bool):
                continue

            try:
                items = tuple(row)
            except TypeError:
                continue

            if len(items) != 6:
                continue

            values = tuple("" if item is None else str(item) for item in items)
            parsed.append(cast(tuple[str, str, str, str, str, str], values))

        return parsed

    def _source_vector_id(self, axiom_hash: str, axiom_id: str) -> str:
        source = axiom_hash or axiom_id
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"phases-axiom:{source}"))

    def _embed_query(self, text: str) -> np.ndarray:
        vector = self._embeddings.embed_query(text)
        return np.array(vector)

    def _extract_axiom_text(self, result: SearchResult) -> str:
        if isinstance(result.payload, dict):
            payload_text = result.payload.get("text")
            if isinstance(payload_text, str):
                return payload_text

        if isinstance(result.metadata, dict):
            metadata_text = result.metadata.get("axiom_text")
            if isinstance(metadata_text, str):
                return metadata_text

        return ""

    def run(self, parameters: AxiomsCrossPaperSimilarityWorkflowParameters):
        output_path = Path(parameters.output_csv_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        collection_name = self._effective_collection_name(parameters)
        search_k = self._effective_search_k(parameters)
        matches_per_axiom = self._effective_matches_per_axiom(parameters)
        score_threshold = self._effective_score_threshold(parameters)

        axioms = self._load_axioms(parameters)
        if len(axioms) == 0:
            logger.info("No axioms found to analyze")
            return

        logger.info(
            "Running cross-paper similarity analysis on "
            f"{len(axioms)} axioms (collection={collection_name}, score_threshold={score_threshold})"
        )

        rows_iter = axioms
        if tqdm is not None:
            rows_iter = tqdm(
                axioms,
                total=len(axioms),
                desc="Analyzing axioms",
                unit="axiom",
            )

        output_columns = [
            "source_axiom_uri",
            "source_axiom_id",
            "source_axiom_hash",
            "source_axiom_text",
            "source_chunk_id",
            "source_path",
            "match_rank",
            "match_score",
            "matched_vector_id",
            "matched_axiom_text",
            "matched_axiom_id",
            "matched_axiom_hash",
            "matched_axiom_uri",
            "matched_chunk_id",
            "matched_chunk_uri",
            "matched_path",
        ]

        total_matches = 0
        sources_with_match = 0
        with output_path.open("w", newline="", encoding="utf-8") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=output_columns)
            writer.writeheader()

            for (
                source_axiom_uri,
                source_axiom_id,
                source_axiom_hash,
                source_axiom_text,
                source_chunk_id,
                source_path,
            ) in rows_iter:
                if not source_axiom_text.strip() or not source_path.strip():
                    continue

                source_vector_id = self._source_vector_id(
                    source_axiom_hash, source_axiom_id
                )

                try:
                    query_vector = self._embed_query(source_axiom_text)
                    raw_results = (
                        self.module.engine.services.vector_store.search_similar(
                            collection_name=collection_name,
                            query_vector=query_vector,
                            k=search_k,
                            score_threshold=score_threshold,
                        )
                    )
                except Exception as exc:
                    logger.error(
                        "Similarity search failed for axiom "
                        f"{source_axiom_id} ({source_path}): {exc}"
                    )
                    continue

                cross_paper_results: list[SearchResult] = []
                for result in raw_results:
                    if result.id == source_vector_id:
                        continue

                    metadata = result.metadata if result.metadata else {}
                    matched_path = str(metadata.get("path", "") or "")
                    if not matched_path:
                        continue
                    if matched_path == source_path:
                        continue

                    cross_paper_results.append(result)
                    if len(cross_paper_results) >= matches_per_axiom:
                        break

                if len(cross_paper_results) == 0:
                    continue

                sources_with_match += 1
                for rank, result in enumerate(cross_paper_results, start=1):
                    metadata = result.metadata if result.metadata else {}
                    writer.writerow(
                        {
                            "source_axiom_uri": source_axiom_uri,
                            "source_axiom_id": source_axiom_id,
                            "source_axiom_hash": source_axiom_hash,
                            "source_axiom_text": source_axiom_text,
                            "source_chunk_id": source_chunk_id,
                            "source_path": source_path,
                            "match_rank": str(rank),
                            "match_score": f"{result.score:.6f}",
                            "matched_vector_id": result.id,
                            "matched_axiom_text": self._extract_axiom_text(result),
                            "matched_axiom_id": metadata.get("axiom_id", ""),
                            "matched_axiom_hash": metadata.get("axiom_hash", ""),
                            "matched_axiom_uri": metadata.get("axiom_uri", ""),
                            "matched_chunk_id": metadata.get("chunk_id", ""),
                            "matched_chunk_uri": metadata.get("chunk_uri", ""),
                            "matched_path": metadata.get("path", ""),
                        }
                    )
                    total_matches += 1

        logger.info(
            "Cross-paper similarity completed: "
            f"sources_with_match={sources_with_match}, total_matches={total_matches}, output={output_path}"
        )
        print(f"Output CSV: {output_path}", flush=True)
        print(f"Axioms analyzed: {len(axioms)}", flush=True)
        print(f"Source axioms with matches: {sources_with_match}", flush=True)
        print(f"Total cross-paper matches: {total_matches}", flush=True)

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

    default_output_path = os.path.join(
        os.path.dirname(__file__), "axioms_cross_paper_similarity.csv"
    )

    parser = argparse.ArgumentParser(
        description="Find similar axioms across different paper paths"
    )
    parser.add_argument(
        "--output-csv-path",
        type=str,
        default=default_output_path,
        help="Path to output CSV file",
    )
    parser.add_argument(
        "--path",
        dest="paths",
        action="append",
        default=None,
        help="Source paper path filter (can be provided multiple times)",
    )
    parser.add_argument(
        "--collection-name",
        type=str,
        default=None,
        help="Axioms vector collection name override",
    )
    parser.add_argument(
        "--search-k",
        type=int,
        default=None,
        help="Number of nearest neighbors retrieved before filtering",
    )
    parser.add_argument(
        "--matches-per-axiom",
        type=int,
        default=None,
        help="Maximum kept matches per source axiom",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=None,
        help="Minimum similarity score",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of source axioms analyzed",
    )

    args = parser.parse_args()

    workflow = AxiomsCrossPaperSimilarityWorkflow(
        AxiomsCrossPaperSimilarityWorkflowConfiguration()
    )
    workflow.run(
        AxiomsCrossPaperSimilarityWorkflowParameters(
            output_csv_path=args.output_csv_path,
            paths=args.paths,
            collection_name=args.collection_name,
            search_k=args.search_k,
            matches_per_axiom=args.matches_per_axiom,
            score_threshold=args.score_threshold,
            limit=args.limit,
        )
    )
