"""Semantic index adapter backed by the engine's vector store + OpenAI embeddings.

Mirrors the ingestion/embedding settings exactly (``text-embedding-3-large`` at
3072 dimensions, collection ``extracted_items``) so query vectors live in the
same space as the stored ``ExtractedItem`` embeddings.
"""

from __future__ import annotations

import numpy as np
from langchain_openai import OpenAIEmbeddings
from naas_abi_core import logger
from naas_abi_core.services.vector_store.IVectorStorePort import SearchResult
from naas_abi_core.services.vector_store.VectorStoreService import VectorStoreService

from phases.app.interfaces import ISemanticIndexPort
from phases.app.models import SemanticMatch

# Must match ExtractedItemsEmbeddingWorkflow / phases.utils.compute_embeddings.
DEFAULT_COLLECTION = "extracted_items"
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSIONS = 3072


class VectorStoreSemanticAdapter(ISemanticIndexPort):
    def __init__(
        self,
        vector_store: VectorStoreService,
        collection_name: str = DEFAULT_COLLECTION,
        embedding_model: str = EMBEDDING_MODEL,
        embedding_dimensions: int = EMBEDDING_DIMENSIONS,
    ):
        self._vector_store = vector_store
        self._collection_name = collection_name
        self._embeddings = OpenAIEmbeddings(
            model=embedding_model, dimensions=embedding_dimensions
        )

    def _embed(self, query: str) -> np.ndarray:
        return np.array(self._embeddings.embed_query(query))

    @staticmethod
    def _item_id(result: SearchResult) -> str | None:
        for source in (result.payload, result.metadata):
            if isinstance(source, dict):
                value = source.get("extracted_item_id")
                if isinstance(value, str) and value:
                    return value
        return None

    @staticmethod
    def _text(result: SearchResult) -> str:
        for source in (result.payload, result.metadata):
            if isinstance(source, dict):
                value = source.get("text")
                if isinstance(value, str) and value:
                    return value
        return ""

    def search(
        self, query: str, k: int, score_threshold: float | None = None
    ) -> list[SemanticMatch]:
        query_vector = self._embed(query)
        try:
            results = self._vector_store.search_similar(
                collection_name=self._collection_name,
                query_vector=query_vector,
                k=k,
                score_threshold=score_threshold,
            )
        except Exception as exc:  # collection missing, store down, etc.
            logger.error(f"Semantic search failed on '{self._collection_name}': {exc}")
            return []

        matches: list[SemanticMatch] = []
        for result in results:
            item_id = self._item_id(result)
            if not item_id:
                # Pre-payload vectors can't be mapped back to a KG entity; skip.
                continue
            matches.append(
                SemanticMatch(
                    extracted_item_id=item_id,
                    text=self._text(result),
                    score=float(result.score),
                )
            )
        return matches
