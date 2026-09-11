"""SearchService — business logic for reverse search.

Orchestrates the semantic index and the extracted-items ports into ranked,
fully-located :class:`SearchHit` results. Knows nothing about Qdrant, DuckDB or
OpenAI. Ported from ``phases.app.domain.SearchService``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from phases_v2.search.interfaces import IExtractedItemsPort, ISemanticIndexPort
from phases_v2.search.models import SearchHit
from phases_v2.search.paths import matches_path

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
        models: list[str] | None = None,
        paths: list[str] | None = None,
    ) -> list[SearchHit]:
        query = (query or "").strip()
        if not query:
            return []
        k = max(1, min(k, _MAX_K))

        fetch = k * _SEMANTIC_OVERFETCH if prompts else k
        paper_ids = self._items.paper_ids_for_paths(paths) if paths else None
        if paper_ids == []:
            return []
        matches = self._index.search(
            query,
            k=fetch,
            score_threshold=score_threshold,
            models=models,
            paper_ids=paper_ids,
        )
        if not matches:
            return []

        locations = self._items.resolve_locations([m.item_id for m in matches])
        wanted = {p for p in prompts} if prompts else None

        hits: list[SearchHit] = []
        for match in matches:
            location = locations.get(match.item_id)
            if paths and (
                location is None or not matches_path(location.source_path, paths)
            ):
                continue
            if models and (location is None or location.model_id not in models):
                continue
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
        models: list[str] | None = None,
        paths: list[str] | None = None,
    ) -> list[SearchHit]:
        tokens = tokenize(query)
        if not tokens:
            return []
        limit = max(1, min(limit, _MAX_K))

        rows = self._items.keyword_search(
            tokens, prompts=prompts, limit=limit, models=models, paths=paths
        )
        return [
            SearchHit.build(
                item_id=item_id,
                extracted_text=text,
                location=location,
                score=None,
            )
            for item_id, text, location in rows
        ]

    def read_view(self, snapshot: int | None = None):
        version = self._items.snapshot() if snapshot is None else snapshot
        return SearchService(self._index, self._items.at_snapshot(version)), version

    def _semantic_hits(
        self, query, score_threshold=None, prompts=None, models=None, paths=None
    ):
        if not query.strip():
            return
        paper_ids = self._items.paper_ids_for_paths(paths) if paths else None
        matches = self._index.search_all(
            query.strip(), score_threshold, models, paper_ids
        )
        seen = set()
        for start in range(0, len(matches), 500):
            batch = matches[start : start + 500]
            locations = self._items.resolve_locations([m.item_id for m in batch])
            for match in batch:
                loc = locations.get(match.item_id)
                if match.item_id in seen:
                    continue
                seen.add(match.item_id)
                if paths and (loc is None or not matches_path(loc.source_path, paths)):
                    continue
                if models and (loc is None or loc.model_id not in models):
                    continue
                if prompts and (loc is None or loc.prompt_name not in prompts):
                    continue
                yield SearchHit.build(
                    item_id=match.item_id,
                    extracted_text=match.text,
                    location=loc,
                    score=match.score,
                )

    def page(
        self,
        mode: str,
        query: str,
        limit: int = 25,
        offset: int = 0,
        score_threshold=None,
        prompts=None,
        models=None,
        paths=None,
    ) -> tuple[list[SearchHit], int]:
        if mode == "keyword":
            tokens = tokenize(query)
            total = self._items.keyword_count(tokens, prompts, models, paths)
            rows = self._items.keyword_search(
                tokens, prompts, limit, models, paths, offset
            )
            return [
                SearchHit.build(item_id=i, extracted_text=t, location=l)
                for i, t, l in rows
            ], total
        hits, total = [], 0
        for hit in self._semantic_hits(query, score_threshold, prompts, models, paths):
            if offset <= total < offset + limit:
                hits.append(hit)
            total += 1
        return hits, total

    def all_hits(
        self,
        mode: str,
        query: str,
        score_threshold=None,
        prompts=None,
        models=None,
        paths=None,
    ) -> Iterator[SearchHit]:
        if mode == "semantic":
            yield from self._semantic_hits(
                query, score_threshold, prompts, models, paths
            )
            return
        tokens, offset = tokenize(query), 0
        while True:
            rows = self._items.keyword_search(
                tokens, prompts, 500, models, paths, offset
            )
            for item_id, text, location in rows:
                yield SearchHit.build(
                    item_id=item_id, extracted_text=text, location=location
                )
            if len(rows) < 500:
                break
            offset += len(rows)

    def list_prompts(self) -> list[str]:
        return self._items.list_prompts()

    def list_models(self) -> list[str]:
        return self._items.list_models()

    def list_paths(self) -> list[str]:
        return self._items.list_paths()
