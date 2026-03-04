"""Axioms search workflow.

Purpose
- Embed a user prompt.
- Search the axioms vector collection.
- Print the best matches with provenance metadata.

How to run (from `abi/`)
- `uv run abi run script abi_phases/phases/workflows/AxiomsSearchWorkflow/AxiomsSearchWorkflow.py --prompt "your prompt"`
- `uv run abi run script abi_phases/phases/workflows/AxiomsSearchWorkflow/AxiomsSearchWorkflow.py --prompt "your prompt" --top-k 10 --collection-name phases_axioms`
"""

from __future__ import annotations

from enum import Enum

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


class AxiomsSearchWorkflowConfiguration(WorkflowConfiguration):
    collection_name: str = "phases_axioms"
    embedding_model_name: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072
    default_top_k: int = 10


class AxiomsSearchWorkflowParameters(WorkflowParameters):
    prompt: str
    top_k: int | None = None
    collection_name: str | None = None
    score_threshold: float | None = None


class AxiomsSearchWorkflow(Workflow[AxiomsSearchWorkflowParameters]):
    module: ABIModule
    _configuration: AxiomsSearchWorkflowConfiguration

    def __init__(self, configuration: AxiomsSearchWorkflowConfiguration):
        super().__init__(configuration)
        self._configuration = configuration
        self.module = ABIModule.get_instance()
        self._embeddings = OpenAIEmbeddings(
            model=configuration.embedding_model_name,
            dimensions=configuration.embedding_dimensions,
        )

    def _collection_name(self, parameters: AxiomsSearchWorkflowParameters) -> str:
        return parameters.collection_name or self._configuration.collection_name

    def _embed_prompt(self, prompt: str) -> np.ndarray:
        vector = self._embeddings.embed_query(prompt)
        return np.array(vector)

    def _extract_axiom_text(self, result: SearchResult) -> str:
        if isinstance(result.payload, dict):
            payload_text = result.payload.get("text")
            if isinstance(payload_text, str) and payload_text.strip():
                return payload_text

        if isinstance(result.metadata, dict):
            metadata_text = result.metadata.get("axiom_text")
            if isinstance(metadata_text, str) and metadata_text.strip():
                return metadata_text

        return "(no text payload)"

    def run(self, parameters: AxiomsSearchWorkflowParameters):
        prompt = parameters.prompt.strip()
        if not prompt:
            raise ValueError("Prompt cannot be empty")

        top_k = parameters.top_k
        if top_k is None:
            top_k = self._configuration.default_top_k
        top_k = max(1, top_k)

        collection_name = self._collection_name(parameters)
        query_vector = self._embed_prompt(prompt)

        logger.debug(
            f"Searching axioms collection '{collection_name}' with top_k={top_k}"
        )

        try:
            results = self.module.engine.services.vector_store.search_similar(
                collection_name=collection_name,
                query_vector=query_vector,
                k=top_k,
                score_threshold=parameters.score_threshold,
            )
        except Exception as exc:
            logger.error(f"Axioms search failed: {exc}")
            print(
                f"Search failed for collection '{collection_name}': {exc}", flush=True
            )
            return

        if len(results) == 0:
            print(
                f"No matches found in collection '{collection_name}'.",
                flush=True,
            )
            return

        print(
            f"Top {len(results)} matches in '{collection_name}' for: {prompt}",
            flush=True,
        )
        for index, result in enumerate(results, start=1):
            metadata = result.metadata or {}
            axiom_text = self._extract_axiom_text(result)
            axiom_id = metadata.get("axiom_id", "")
            axiom_hash = metadata.get("axiom_hash", "")
            path = metadata.get("path", "")
            chunk_id = metadata.get("chunk_id", "")

            print(f"\n{index}. score={result.score:.4f}", flush=True)
            print(f"   axiom_id={axiom_id}", flush=True)
            print(f"   axiom_hash={axiom_hash}", flush=True)
            print(f"   chunk_id={chunk_id}", flush=True)
            print(f"   path={path}", flush=True)
            print(f"   axiom={axiom_text}", flush=True)

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

    parser = argparse.ArgumentParser(description="Search the axioms vector collection")
    parser.add_argument(
        "--prompt",
        type=str,
        required=True,
        help="Prompt to embed and search",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Number of matches to return (default: 10)",
    )
    parser.add_argument(
        "--collection-name",
        type=str,
        default=None,
        help="Vector collection name override",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=None,
        help="Optional minimum score filter",
    )

    args = parser.parse_args()

    workflow = AxiomsSearchWorkflow(AxiomsSearchWorkflowConfiguration())
    workflow.run(
        AxiomsSearchWorkflowParameters(
            prompt=args.prompt,
            top_k=args.top_k,
            collection_name=args.collection_name,
            score_threshold=args.score_threshold,
        )
    )
