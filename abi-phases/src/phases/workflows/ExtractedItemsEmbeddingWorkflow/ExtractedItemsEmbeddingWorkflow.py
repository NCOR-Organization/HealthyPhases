"""Embed every phases-doc:ExtractedItem so they can be searched.

Reads ExtractedItem instances from the extractions named graph, computes
an embedding of `extracted_text` for each one, and stores them in a vector
store collection keyed by `extracted_item_id`.

Idempotent: items already embedded (tracked via the cache service) are
skipped on re-run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import APIRouter
from langchain_core.tools import StructuredTool
from naas_abi_core import logger
from naas_abi_core.services.cache.CacheFactory import CacheFactory
from naas_abi_core.workflow.workflow import (
    Workflow,
    WorkflowConfiguration,
    WorkflowParameters,
)
import rdflib

from phases import ABIModule
from phases.utils import compute_embeddings


EXTRACTIONS_GRAPH = rdflib.URIRef(
    "http://ontology.naas.ai/graph/phases/extractions"
)
COLLECTION_NAME = "extracted_items"
EMBEDDING_DIMENSION = 3072

# Stable namespace used to derive Qdrant-compatible UUIDs from extracted_item_ids.
EXTRACTED_ITEM_UUID_NAMESPACE = uuid.UUID("8b6a3f8a-1a3f-4b2a-9b1f-5c2c2b1f7d10")


def _point_id_for(extracted_item_id: str) -> str:
    return str(uuid.uuid5(EXTRACTED_ITEM_UUID_NAMESPACE, extracted_item_id))


@dataclass
class ExtractedItemsEmbeddingWorkflowConfiguration(WorkflowConfiguration):
    collection_name: str = COLLECTION_NAME
    batch_size: int = 64


class ExtractedItemsEmbeddingWorkflowParameters(WorkflowParameters):
    extraction_id: str | None = None
    """Optional: restrict embedding to items produced by this Extraction id
    (the same value persisted via phases-doc:extraction_id). None = all items."""
    limit: int | None = None


class ExtractedItemsEmbeddingWorkflow(
    Workflow[ExtractedItemsEmbeddingWorkflowParameters]
):
    module: ABIModule

    def __init__(
        self, configuration: ExtractedItemsEmbeddingWorkflowConfiguration
    ):
        super().__init__(configuration)
        self.__configuration = configuration
        self.module = ABIModule.get_instance()
        self.__cache = CacheFactory.CacheFS_find_storage(
            subpath="extracted_items_embedding"
        )

    def _build_query(
        self, parameters: ExtractedItemsEmbeddingWorkflowParameters
    ) -> str:
        extraction_filter = ""
        if parameters.extraction_id:
            extraction_filter = (
                f"\n        ?item phases-doc:extracted_by ?extraction .\n"
                f"        ?extraction phases-doc:extraction_id "
                f"{rdflib.Literal(parameters.extraction_id).n3()} ."
            )

        limit_clause = (
            f"\nLIMIT {parameters.limit}" if parameters.limit is not None else ""
        )

        return f"""PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>
SELECT ?item ?id ?text WHERE {{
    GRAPH <{EXTRACTIONS_GRAPH}> {{
        ?item a phases-doc:ExtractedItem ;
            phases-doc:extracted_item_id ?id ;
            phases-doc:extracted_text ?text .{extraction_filter}
    }}
}}
ORDER BY ?id{limit_clause}"""

    def run(
        self, parameters: ExtractedItemsEmbeddingWorkflowParameters
    ) -> int:
        rows = list(
            self.module.engine.services.triple_store.query(
                self._build_query(parameters)
            )
        )
        logger.info(f"ExtractedItem candidates: {len(rows)}")

        # Filter out items we have already embedded.
        pending: list[tuple[str, str]] = []
        for _, item_id, text in rows:
            id_str = str(item_id)
            if self.__cache.exists(f"embedded:{id_str}"):
                continue
            pending.append((id_str, str(text)))

        logger.info(
            f"ExtractedItem to embed: {len(pending)} (skipped "
            f"{len(rows) - len(pending)} already-embedded)"
        )
        if not pending:
            return 0

        self.module.engine.services.vector_store.ensure_collection(
            collection_name=self.__configuration.collection_name,
            dimension=EMBEDDING_DIMENSION,
        )

        batch_size = max(1, self.__configuration.batch_size)
        total_embedded = 0

        for batch_start in range(0, len(pending), batch_size):
            batch = pending[batch_start : batch_start + batch_size]
            item_ids = [item_id for item_id, _ in batch]
            texts = [text for _, text in batch]
            # Qdrant requires unsigned int or UUID point IDs; our extracted_item_ids
            # are sha256 hex. Derive a deterministic UUID5 and keep the original
            # id in the payload so search results map back to KG entities.
            point_ids = [_point_id_for(item_id) for item_id in item_ids]
            payloads = [
                {"extracted_item_id": item_id, "text": text}
                for item_id, text in batch
            ]

            logger.debug(
                f"Embedding batch {batch_start // batch_size + 1} "
                f"({len(batch)} items)"
            )
            embeddings = compute_embeddings(texts)

            self.module.engine.services.vector_store.add_documents(
                self.__configuration.collection_name,
                point_ids,
                embeddings,
                payloads=payloads,
            )

            for item_id in item_ids:
                self.__cache.set_json(f"embedded:{item_id}", {"id": item_id})

            total_embedded += len(batch)

        logger.info(
            f"Embedded {total_embedded} ExtractedItem(s) into "
            f"'{self.__configuration.collection_name}'"
        )
        return total_embedded

    def as_tools(self) -> list[StructuredTool]:
        return []

    def as_api(self, router: APIRouter):
        return []


if __name__ == "__main__":
    workflow = ExtractedItemsEmbeddingWorkflow(
        ExtractedItemsEmbeddingWorkflowConfiguration()
    )
    workflow.run(ExtractedItemsEmbeddingWorkflowParameters())
