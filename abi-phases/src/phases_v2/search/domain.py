"""SearchService — business logic for reverse search.

Orchestrates the semantic index and the extracted-items ports into ranked,
fully-located :class:`SearchHit` results. Knows nothing about Qdrant, DuckDB or
OpenAI. Ported from ``phases.app.domain.SearchService``.
"""

from __future__ import annotations

import re

from phases_v2.search.interfaces import IExtractedItemsPort, ISemanticIndexPort
from phases_v2.search.models import SearchHit

# Semantic search over-fetches before optional prompt filtering so a tight
# facet doesn't starve the result set.
_SEMANTIC_OVERFETCH = 4
_MAX_K = 100


def tokenize(query: str) -> list[str]:
    """Split a keyword query into word tokens (kept lowercase, deduped)."""
    seen: set[str] = set()
    tokens: list[str] = []
    for raw in re.findall(r"\w+", query.lower()):
        if raw and raw not in seen:
            seen.add(raw)
            tokens.append(raw)
    return tokens


class SearchService:
    def __init__(
        self,
        semantic_index: ISemanticIndexPort,
        extracted_items: IExtractedItemsPort,
    ):
        self._index = semantic_index
        self._items = extracted_items

    def semantic_search(
        self,
        query: str,
        k: int = 10,
        score_threshold: float | None = None,
        prompts: list[str] | None = None,
    ) -> list[SearchHit]:
        query = (query or "").strip()
        if not query:
            return []
        k = max(1, min(k, _MAX_K))

        fetch = k * _SEMANTIC_OVERFETCH if prompts else k
        matches = self._index.search(query, k=fetch, score_threshold=score_threshold)
        if not matches:
            return []

        locations = self._items.resolve_locations([m.item_id for m in matches])
        wanted = {p for p in prompts} if prompts else None

        hits: list[SearchHit] = []
        for match in matches:
            location = locations.get(match.item_id)
            if wanted is not None and (
                location is None or location.prompt_name not in wanted
            ):
                continue
            hits.append(
                SearchHit.build(
                    item_id=match.item_id,
                    extracted_text=match.text,
                    location=location,
                    score=match.score,
                )
            )
            if len(hits) >= k:
                break
        return hits

    def keyword_search(
        self,
        query: str,
        limit: int = 25,
        prompts: list[str] | None = None,
    ) -> list[SearchHit]:
        tokens = tokenize(query)
        if not tokens:
            return []
        limit = max(1, min(limit, _MAX_K))

        rows = self._items.keyword_search(tokens, prompts=prompts, limit=limit)
        return [
            SearchHit.build(
                item_id=item_id,
                extracted_text=text,
                location=location,
                score=None,
            )
            for item_id, text, location in rows
        ]

    def list_prompts(self) -> list[str]:
        return self._items.list_prompts()
