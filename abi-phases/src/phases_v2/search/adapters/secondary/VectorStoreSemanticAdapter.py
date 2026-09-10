"""Semantic index adapter backed by the engine's vector store.

Reads the ``phases_v2_extracted_items`` collection that
``phases_v2.projection.vectors`` writes, and embeds the query with the same
:class:`~phases_v2.projection.interfaces.Embedder` the projector uses — so a
query vector lands in the same space as the stored item embeddings without
this module repeating the model/dimension choice.
"""

from __future__ import annotations

import numpy as np
from naas_abi_core import logger
from naas_abi_core.services.vector_store.IVectorStorePort import SearchResult
from naas_abi_core.services.vector_store.VectorStoreService import VectorStoreService

from phases_v2.projection.interfaces import Embedder
from phases_v2.projection.vectors import ITEMS_COLLECTION
from phases_v2.search.models import SemanticMatch


class VectorStoreSemanticAdapter:
    def __init__(
        self,
        vector_store: VectorStoreService,
        embedder: Embedder,
        collection_name: str = ITEMS_COLLECTION,
    ):
        self._vector_store = vector_store
        self._embedder = embedder
        self._collection_name = collection_name

    @staticmethod
    def _item_id(result: SearchResult) -> str | None:
        for source in (result.metadata, result.payload):
            if isinstance(source, dict):
                value = source.get("item_id") or source.get("document_id")
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
        self,
        query: str,
        k: int,
        score_threshold: float | None = None,
        models: list[str] | None = None,
    ) -> list[SemanticMatch]:
        [vector] = self._embedder.embed([query])
        query_vector = np.asarray(vector, dtype=np.float32)
        try:
            # The vector port supports equality filters. Take top-k per model,
            # then combine them, so other models cannot crowd out selected ones.
            selected_models = list(dict.fromkeys(models)) if models else [None]
            results = []
            for model in selected_models:
                results.extend(
                    self._vector_store.search_similar(
                        collection_name=self._collection_name,
                        query_vector=query_vector,
                        k=k,
                        filter={"model_id": model} if model is not None else None,
                        score_threshold=score_threshold,
                    )
                )
            results = sorted(results, key=lambda result: result.score, reverse=True)[:k]
        except Exception as exc:  # noqa: BLE001 - collection missing, store down, etc.
            logger.error(f"Semantic search failed on '{self._collection_name}': {exc}")
            return []

        matches: list[SemanticMatch] = []
        for result in results:
            item_id = self._item_id(result)
            if not item_id:
                # Pre-payload vectors can't be mapped back to an extracted item.
                continue
            matches.append(
                SemanticMatch(
                    item_id=item_id, text=self._text(result), score=float(result.score)
                )
            )
        return matches
