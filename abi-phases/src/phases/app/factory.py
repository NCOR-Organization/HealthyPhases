"""Factory wiring the reverse-search domain from the running engine.

Keeps the composition root in one place: secondary adapters are built from the
:class:`ABIModule` engine services and injected into :class:`SearchService`.
"""

from __future__ import annotations

from phases.app.adapters.secondary.TripleStoreKnowledgeGraphAdapter import (
    TripleStoreKnowledgeGraphAdapter,
)
from phases.app.adapters.secondary.VectorStoreSemanticAdapter import (
    VectorStoreSemanticAdapter,
)
from phases.app.domain import SearchService


class SearchServiceFactory:
    @staticmethod
    def from_engine(engine) -> SearchService:
        """Build a :class:`SearchService` from an engine proxy (``module.engine``)."""
        services = engine.services
        return SearchService(
            semantic_index=VectorStoreSemanticAdapter(services.vector_store),
            knowledge_graph=TripleStoreKnowledgeGraphAdapter(services.triple_store),
        )
