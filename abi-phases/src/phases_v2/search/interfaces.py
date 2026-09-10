"""Ports for reverse search, stated without naming a store.

The domain (:class:`phases_v2.search.domain.SearchService`) talks only to
these; secondary adapters in ``phases_v2.search.adapters.secondary`` implement
them. Datasets are the system of record for this module (see the README), so
``IExtractedItemsPort`` reads the ``extracted_items`` dataset rather than the
projected triple store — it needs no projection to have run and can never lag
behind what was actually extracted.
"""

from __future__ import annotations

from typing import Protocol

from phases_v2.search.models import ItemLocation, SemanticMatch


class ISemanticIndexPort(Protocol):
    """Vector search over embedded extracted items.

    Implementations own the embedding of the query text and the similarity
    search, so the domain stays free of any embedding/vector technology.
    """

    def search(
        self,
        query: str,
        k: int,
        score_threshold: float | None = None,
        models: list[str] | None = None,
        paper_ids: list[str] | None = None,
    ) -> list[SemanticMatch]:
        """Return the ``k`` most similar extracted items to ``query``."""
        ...


class IExtractedItemsPort(Protocol):
    """Read access to the extracted-item corpus."""

    def resolve_locations(self, item_ids: list[str]) -> dict[str, ItemLocation]:
        """Map each ``item_id`` to its paper + chunk provenance."""
        ...

    def keyword_search(
        self,
        tokens: list[str],
        prompts: list[str] | None,
        limit: int,
        models: list[str] | None = None,
        paths: list[str] | None = None,
    ) -> list[tuple[str, str, ItemLocation]]:
        """Word-presence search over extracted text.

        Returns ``(item_id, text, location)`` tuples for items whose text
        contains *every* token (case-insensitive), optionally restricted to
        the given prompt ``prompts`` (by name).
        """
        ...

    def list_prompts(self) -> list[str]:
        """Prompt names actually present in the corpus (for facets)."""
        ...

    def list_models(self) -> list[str]:
        """Extraction model IDs actually present in the corpus."""
        ...

    def list_paths(self) -> list[str]:
        """Source folders and their parents present in extracted items."""
        ...

    def paper_ids_for_paths(self, paths: list[str]) -> list[str]:
        """Resolve folders, including descendants, to IDs for vector filtering."""
        ...
