"""Match questionnaire rows against axioms vectors.

Purpose
- Read a CSV file with a `Questionnaire` column.
- Embed each questionnaire value.
- Search the axioms vector collection.
- Write a new CSV with top-k matches (one output row per match).

How to run (from `abi/`)
- `uv run abi run script abi_phases/phases/workflows/SolitudeassessmentinstrumentsandtermsWorkflow/SolitudeassessmentinstrumentsandtermsWorkflow.py`
- `uv run abi run script abi_phases/phases/workflows/SolitudeassessmentinstrumentsandtermsWorkflow/SolitudeassessmentinstrumentsandtermsWorkflow.py --top-k 5 --collection-name phases_axioms`
"""

from __future__ import annotations

import csv
import os
from enum import Enum
from pathlib import Path

import numpy as np
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


class SolitudeAssessmentInstrumentsAndTermsWorkflowConfiguration(WorkflowConfiguration):
    embedding_model_name: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072
    collection_name: str = "phases_axioms"
    questionnaire_column: str = "Questionnaire"
    top_k: int = 5
    score_threshold: float | None = None


class SolitudeAssessmentInstrumentsAndTermsWorkflowParameters(WorkflowParameters):
    input_csv_path: str
    output_csv_path: str
    questionnaire_column: str | None = None
    collection_name: str | None = None
    top_k: int | None = None
    score_threshold: float | None = None


class SolitudeAssessmentInstrumentsAndTermsWorkflow(
    Workflow[SolitudeAssessmentInstrumentsAndTermsWorkflowParameters]
):
    module: ABIModule
    _configuration: SolitudeAssessmentInstrumentsAndTermsWorkflowConfiguration

    def __init__(
        self, configuration: SolitudeAssessmentInstrumentsAndTermsWorkflowConfiguration
    ):
        super().__init__(configuration)
        self._configuration = configuration
        self.module = ABIModule.get_instance()
        self._embeddings = OpenAIEmbeddings(
            model=configuration.embedding_model_name,
            dimensions=configuration.embedding_dimensions,
        )

    def _effective_questionnaire_column(
        self, parameters: SolitudeAssessmentInstrumentsAndTermsWorkflowParameters
    ) -> str:
        return (
            parameters.questionnaire_column or self._configuration.questionnaire_column
        )

    def _effective_collection_name(
        self, parameters: SolitudeAssessmentInstrumentsAndTermsWorkflowParameters
    ) -> str:
        return parameters.collection_name or self._configuration.collection_name

    def _effective_top_k(
        self, parameters: SolitudeAssessmentInstrumentsAndTermsWorkflowParameters
    ) -> int:
        top_k = parameters.top_k
        if top_k is None:
            top_k = self._configuration.top_k
        return max(1, top_k)

    def _effective_score_threshold(
        self, parameters: SolitudeAssessmentInstrumentsAndTermsWorkflowParameters
    ) -> float | None:
        if parameters.score_threshold is not None:
            return parameters.score_threshold
        return self._configuration.score_threshold

    def _embed_query(self, text: str) -> np.ndarray:
        embedding = self._embeddings.embed_query(text)
        return np.array(embedding)

    def _search_axioms(
        self,
        query_text: str,
        collection_name: str,
        top_k: int,
        score_threshold: float | None,
    ) -> list[SearchResult]:
        if not query_text.strip():
            return []

        query_vector = self._embed_query(query_text)
        return self.module.engine.services.vector_store.search_similar(
            collection_name=collection_name,
            query_vector=query_vector,
            k=top_k,
            score_threshold=score_threshold,
        )

    def run(self, parameters: SolitudeAssessmentInstrumentsAndTermsWorkflowParameters):
        input_path = Path(parameters.input_csv_path)
        output_path = Path(parameters.output_csv_path)

        questionnaire_column = self._effective_questionnaire_column(parameters)
        collection_name = self._effective_collection_name(parameters)
        top_k = self._effective_top_k(parameters)
        score_threshold = self._effective_score_threshold(parameters)

        if not input_path.exists():
            raise FileNotFoundError(f"Input CSV not found: {input_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Reading input CSV: {input_path}")
        with input_path.open("r", newline="", encoding="utf-8") as input_file:
            reader = csv.DictReader(input_file)
            source_columns = reader.fieldnames or []
            if questionnaire_column not in source_columns:
                raise ValueError(
                    f"Missing required column '{questionnaire_column}' in CSV: {input_path}"
                )

            match_columns = [
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
            output_columns = list(source_columns) + match_columns

            logger.info(
                f"Writing output CSV: {output_path} (top_k={top_k}, collection={collection_name})"
            )
            with output_path.open("w", newline="", encoding="utf-8") as output_file:
                writer = csv.DictWriter(output_file, fieldnames=output_columns)
                writer.writeheader()

                source_rows = list(reader)
                rows_iter = source_rows
                if tqdm is not None:
                    rows_iter = tqdm(
                        source_rows,
                        total=len(source_rows),
                        desc="Matching questionnaire rows",
                        unit="row",
                    )

                processed_rows = 0
                written_rows = 0
                for source_row in rows_iter:
                    processed_rows += 1
                    questionnaire_value = source_row.get(questionnaire_column, "") or ""

                    try:
                        matches = self._search_axioms(
                            query_text=questionnaire_value,
                            collection_name=collection_name,
                            top_k=top_k,
                            score_threshold=score_threshold,
                        )
                    except Exception as exc:
                        logger.error(
                            "Axioms search failed for questionnaire row "
                            f"{processed_rows}: {exc}"
                        )
                        matches = []

                    for rank in range(1, top_k + 1):
                        result = matches[rank - 1] if rank - 1 < len(matches) else None
                        metadata = result.metadata if result and result.metadata else {}
                        payload = result.payload if result and result.payload else {}

                        output_row = dict(source_row)
                        output_row.update(
                            {
                                "match_rank": str(rank),
                                "match_score": f"{result.score:.6f}" if result else "",
                                "matched_vector_id": result.id if result else "",
                                "matched_axiom_text": payload.get("text", "")
                                if isinstance(payload, dict)
                                else "",
                                "matched_axiom_id": metadata.get("axiom_id", ""),
                                "matched_axiom_hash": metadata.get("axiom_hash", ""),
                                "matched_axiom_uri": metadata.get("axiom_uri", ""),
                                "matched_chunk_id": metadata.get("chunk_id", ""),
                                "matched_chunk_uri": metadata.get("chunk_uri", ""),
                                "matched_path": metadata.get("path", ""),
                            }
                        )
                        writer.writerow(output_row)
                        written_rows += 1

        logger.info(
            f"Completed CSV matching: input rows={processed_rows}, output rows={written_rows}"
        )
        print(f"Input CSV: {input_path}", flush=True)
        print(f"Output CSV: {output_path}", flush=True)
        print(f"Processed rows: {processed_rows}", flush=True)
        print(f"Written rows: {written_rows}", flush=True)

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

    default_input_path = os.path.join(
        os.path.dirname(__file__),
        "Solitude Assessment Instruments & Terms - Sheet1.csv",
    )
    default_output_path = os.path.join(
        os.path.dirname(__file__),
        "Solitude Assessment Instruments & Terms - Sheet1.with_axiom_matches.csv",
    )

    parser = argparse.ArgumentParser(
        description=(
            "For each Questionnaire value, search top axioms and write expanded CSV"
        )
    )
    parser.add_argument(
        "--input-csv-path",
        type=str,
        default=default_input_path,
        help="Path to source CSV file",
    )
    parser.add_argument(
        "--output-csv-path",
        type=str,
        default=default_output_path,
        help="Path to output CSV file",
    )
    parser.add_argument(
        "--questionnaire-column",
        type=str,
        default=None,
        help="Column name to embed and search (default: Questionnaire)",
    )
    parser.add_argument(
        "--collection-name",
        type=str,
        default=None,
        help="Axioms vector collection name override",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Number of matches per input row (default: 5)",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=None,
        help="Optional minimum score filter",
    )

    args = parser.parse_args()

    workflow = SolitudeAssessmentInstrumentsAndTermsWorkflow(
        SolitudeAssessmentInstrumentsAndTermsWorkflowConfiguration()
    )
    workflow.run(
        SolitudeAssessmentInstrumentsAndTermsWorkflowParameters(
            input_csv_path=args.input_csv_path,
            output_csv_path=args.output_csv_path,
            questionnaire_column=args.questionnaire_column,
            collection_name=args.collection_name,
            top_k=args.top_k,
            score_threshold=args.score_threshold,
        )
    )
