"""Wiring for the reverse-search domain.

``semantic_index`` and ``extracted_items`` can be overridden — same shape as
``projection.factory.project_to_vectors`` — so callers (tests, mainly) can
substitute a fake without needing a real embedding API key.
"""

from __future__ import annotations

from phases_v2 import PhasesV2Configuration
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.projection.embedding_factory import embedder_for
from phases_v2.search.adapters.secondary.DatasetExtractedItemsAdapter import (
    DatasetExtractedItemsAdapter,
)
from phases_v2.search.adapters.secondary.VectorStoreSemanticAdapter import (
    VectorStoreSemanticAdapter,
)
from phases_v2.search.domain import SearchService
from phases_v2.search.interfaces import IExtractedItemsPort, ISemanticIndexPort


def search_service(
    engine,
    *,
    configuration: PhasesV2Configuration | None = None,
    semantic_index: ISemanticIndexPort | None = None,
    extracted_items: IExtractedItemsPort | None = None,
) -> SearchService:
    return SearchService(
        semantic_index=semantic_index
        or VectorStoreSemanticAdapter(
            engine.services.vector_store, embedder_for(engine, configuration=configuration)
        ),
        extracted_items=extracted_items
        or DatasetExtractedItemsAdapter(DatasetRowStore(engine.services.dataset)),
    )
