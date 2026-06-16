"""Ports for the reverse-search domain.

The domain (:class:`phases.app.domain.SearchService`) talks only to these
abstractions, never to Qdrant / SPARQL / OpenAI directly. Secondary adapters in
``phases.app.adapters.secondary`` implement them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from phases.app.models import ItemLocation, SemanticMatch


class ISemanticIndexPort(ABC):
    """Vector search over embedded extracted items.

    Implementations own the embedding of the query text and the similarity
    search, so the domain stays free of any embedding/vector technology.
    """

    @abstractmethod
    def search(
        self, query: str, k: int, score_threshold: float | None = None
    ) -> list[SemanticMatch]:
        """Return the ``k`` most similar extracted items to ``query``."""


class IKnowledgeGraphPort(ABC):
    """Read access to the extracted-item knowledge graph."""

    @abstractmethod
    def resolve_locations(self, item_ids: list[str]) -> dict[str, ItemLocation]:
        """Map each ``extracted_item_id`` to its paper + chunk provenance."""

    @abstractmethod
    def keyword_search(
        self,
        tokens: list[str],
        pipelines: list[str] | None,
        limit: int,
    ) -> list[tuple[str, str, ItemLocation]]:
        """Word-presence search over ``extracted_text``.

        Returns ``(extracted_item_id, extracted_text, location)`` tuples for
        items whose text contains *every* token (case-insensitive), optionally
        restricted to the given extraction ``pipelines``.
        """

    @abstractmethod
    def list_pipelines(self) -> list[str]:
        """Distinct extraction pipeline names present in the graph (for facets)."""
