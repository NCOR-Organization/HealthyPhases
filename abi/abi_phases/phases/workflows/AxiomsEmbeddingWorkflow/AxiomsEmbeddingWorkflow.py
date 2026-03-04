"""Axioms embedding workflow.

Purpose
- Read extracted axioms from the triple store.
- Compute embeddings for each axiom text.
- Upsert vectors into a dedicated vector-store collection.

How to run (from `abi/`)
- `uv run abi run script abi_phases/phases/workflows/AxiomsEmbeddingWorkflow/AxiomsEmbeddingWorkflow.py`
- `uv run abi run script abi_phases/phases/workflows/AxiomsEmbeddingWorkflow/AxiomsEmbeddingWorkflow.py --collection-name phases_axioms --recreate-collection`
- `uv run abi run script abi_phases/phases/workflows/AxiomsEmbeddingWorkflow/AxiomsEmbeddingWorkflow.py --path ".../paper1.pdf" --path ".../paper2.pdf" --limit 200`
"""

from __future__ import annotations

from enum import Enum
from typing import cast
import uuid

import numpy as np
import rdflib
from fastapi import APIRouter
from langchain_core.tools import BaseTool
from langchain_openai import OpenAIEmbeddings
from naas_abi_core import logger
from naas_abi_core.workflow.workflow import (
    Workflow,
    WorkflowConfiguration,
    WorkflowParameters,
)

from abi_phases.phases import ABIModule


class AxiomsEmbeddingWorkflowConfiguration(WorkflowConfiguration):
    collection_name: str = "phases_axioms"
    embedding_model_name: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072
    distance_metric: str = "cosine"
    default_limit: int | None = None
    batch_size: int = 64


class AxiomsEmbeddingWorkflowParameters(WorkflowParameters):
    paths: list[str] | None = None
    limit: int | None = None
    collection_name: str | None = None
    recreate_collection: bool = False
    dry_run: bool = False


class AxiomsEmbeddingWorkflow(Workflow[AxiomsEmbeddingWorkflowParameters]):
    module: ABIModule
    _configuration: AxiomsEmbeddingWorkflowConfiguration

    def __init__(self, configuration: AxiomsEmbeddingWorkflowConfiguration):
        super().__init__(configuration)
        self._configuration = configuration
        self.module = ABIModule.get_instance()
        self._embeddings = OpenAIEmbeddings(
            model=configuration.embedding_model_name,
            dimensions=configuration.embedding_dimensions,
        )

    def _collection_name(self, parameters: AxiomsEmbeddingWorkflowParameters) -> str:
        return parameters.collection_name or self._configuration.collection_name

    def _build_axioms_query(self, parameters: AxiomsEmbeddingWorkflowParameters) -> str:
        path_clause = ""
        if parameters.paths:
            values = " ".join(rdflib.Literal(path).n3() for path in parameters.paths)
            path_clause = f"VALUES ?path {{ {values} }}"

        limit = parameters.limit
        if limit is None:
            limit = self._configuration.default_limit
        limit_clause = f"LIMIT {limit}" if limit is not None else ""

        return f"""PREFIX phases-ax: <http://purl.obolibrary.org/obo/phases/axioms.owl#>
PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>

SELECT ?axiom ?axiom_id ?axiom_hash ?axiom_text ?chunk ?chunk_id ?path ?model ?prompt_version ?creation_time WHERE {{
    ?axiom a phases-ax:ExtractedAxiom ;
        phases-ax:axiom_id ?axiom_id ;
        phases-ax:axiom_hash ?axiom_hash ;
        phases-ax:axiom_text ?axiom_text ;
        phases-ax:axiom_from_chunk ?chunk .
    OPTIONAL {{ ?axiom phases-ax:source_chunk_id ?chunk_id . }}
    OPTIONAL {{ ?axiom phases-ax:generated_by_model ?model . }}
    OPTIONAL {{ ?axiom phases-ax:prompt_version ?prompt_version . }}
    OPTIONAL {{ ?axiom phases-ax:creation_time ?creation_time . }}
    OPTIONAL {{
        ?chunk phases-doc:chunk_of ?pdf_paper_file .
        ?pdf_paper_file phases-doc:path ?path .
        {path_clause}
    }}
}}
ORDER BY ?axiom_id
{limit_clause}"""

    def _load_axioms(
        self, parameters: AxiomsEmbeddingWorkflowParameters
    ) -> list[tuple[str, str, str, str, str, str, str, str, str, str]]:
        rows = self.module.engine.services.triple_store.query(
            self._build_axioms_query(parameters)
        )
        parsed_rows: list[tuple[str, str, str, str, str, str, str, str, str, str]] = []

        for row in rows:
            if isinstance(row, bool):
                continue

            try:
                items = tuple(row)
            except TypeError:
                continue

            if len(items) != 10:
                continue

            values = tuple("" if value is None else str(value) for value in items)
            parsed_rows.append(
                cast(tuple[str, str, str, str, str, str, str, str, str, str], values)
            )

        return parsed_rows

    def _embed_texts(self, texts: list[str]) -> list[np.ndarray]:
        embeddings = self._embeddings.embed_documents(texts)
        return [np.array(vector) for vector in embeddings]

    def _vector_id_from_axiom(self, axiom_hash: str, axiom_id: str) -> str:
        source = axiom_hash or axiom_id
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"phases-axiom:{source}"))

    def _chunked(
        self, rows: list[tuple[str, ...]], size: int
    ) -> list[list[tuple[str, ...]]]:
        return [rows[index : index + size] for index in range(0, len(rows), size)]

    def run(self, parameters: AxiomsEmbeddingWorkflowParameters):
        logger.debug("Running axioms embedding workflow")

        rows = self._load_axioms(parameters)
        logger.debug(f"Axioms embedding workflow candidate axioms: {len(rows)}")
        if len(rows) == 0:
            logger.info("No axioms found to embed")
            return

        collection_name = self._collection_name(parameters)
        self.module.engine.services.vector_store.ensure_collection(
            collection_name=collection_name,
            dimension=self._configuration.embedding_dimensions,
            distance_metric=self._configuration.distance_metric,
            recreate=parameters.recreate_collection,
        )

        if parameters.dry_run:
            logger.info(
                f"Dry run enabled: would embed {len(rows)} axioms into {collection_name}"
            )
            return

        batch_size = max(1, self._configuration.batch_size)
        embedded_count = 0

        for batch in self._chunked(rows, batch_size):
            ids: list[str] = []
            texts: list[str] = []
            metadata: list[dict[str, str]] = []
            payloads: list[dict[str, str]] = []

            for (
                axiom_uri,
                axiom_id,
                axiom_hash,
                axiom_text,
                chunk_uri,
                chunk_id,
                path,
                model,
                prompt_version,
                creation_time,
            ) in batch:
                vector_id = self._vector_id_from_axiom(axiom_hash, axiom_id)
                ids.append(vector_id)
                texts.append(axiom_text)
                metadata.append(
                    {
                        "axiom_uri": axiom_uri,
                        "axiom_id": axiom_id,
                        "axiom_hash": axiom_hash,
                        "chunk_uri": chunk_uri,
                        "chunk_id": chunk_id,
                        "path": path,
                        "generated_by_model": model,
                        "prompt_version": prompt_version,
                        "creation_time": creation_time,
                    }
                )
                payloads.append({"text": axiom_text})

            vectors = self._embed_texts(texts)

            self.module.engine.services.vector_store.add_documents(
                collection_name=collection_name,
                ids=ids,
                vectors=vectors,
                metadata=metadata,
                payloads=payloads,
            )
            embedded_count += len(batch)

        logger.info(
            f"Axioms embedding workflow completed; embedded axioms: {embedded_count}"
        )

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

    parser = argparse.ArgumentParser(description="Embed extracted axioms")
    parser.add_argument(
        "--path",
        dest="paths",
        action="append",
        default=None,
        help="Paper path to include (can be provided multiple times)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of axioms to process",
    )
    parser.add_argument(
        "--collection-name",
        type=str,
        default=None,
        help="Vector collection name override",
    )
    parser.add_argument(
        "--recreate-collection",
        action="store_true",
        help="Delete and recreate collection before upserting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List candidates and collection setup without storing vectors",
    )

    args = parser.parse_args()

    workflow = AxiomsEmbeddingWorkflow(AxiomsEmbeddingWorkflowConfiguration())
    workflow.run(
        AxiomsEmbeddingWorkflowParameters(
            paths=args.paths,
            limit=args.limit,
            collection_name=args.collection_name,
            recreate_collection=args.recreate_collection,
            dry_run=args.dry_run,
        )
    )
