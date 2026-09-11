"""In-memory fakes implementing the search ports.

Used by the domain tests and by the generic port-contract checks in
``contracts.py`` so any real adapter can be validated against the same
expectations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from phases_v2.search.models import ItemLocation, SemanticMatch
from phases_v2.search.paths import matches_path, parent_paths


@dataclass
class FakeItem:
    item_id: str
    text: str
    location: ItemLocation
    # Higher = more similar to any query, for deterministic semantic ordering.
    similarity: float = 0.5


@dataclass
class FakeSemanticIndex:
    items: list[FakeItem] = field(default_factory=list)

    def search_all(self, query, score_threshold=None, models=None, paper_ids=None):
        return sorted(
            self.search(query, len(self.items), score_threshold, models, paper_ids),
            key=lambda hit: (-hit.score, hit.item_id),
        )

    def search(
        self,
        query: str,
        k: int,
        score_threshold: float | None = None,
        models: list[str] | None = None,
        paper_ids: list[str] | None = None,
    ) -> list[SemanticMatch]:
        ranked = sorted(self.items, key=lambda i: i.similarity, reverse=True)
        out = [
            SemanticMatch(item_id=i.item_id, text=i.text, score=i.similarity)
            for i in ranked
            if paper_ids is None or i.location.paper_id in paper_ids
            if not models or i.location.model_id in models
            if score_threshold is None or i.similarity >= score_threshold
        ]
        return out[:k]


@dataclass
class FakeExtractedItems:
    items: list[FakeItem] = field(default_factory=list)

    def snapshot(self):
        return None

    def at_snapshot(self, snapshot):
        from copy import deepcopy

        return deepcopy(self)

    def keyword_count(self, tokens, prompts=None, models=None, paths=None):
        return len(self.keyword_search(tokens, prompts, len(self.items), models, paths))

    def resolve_locations(self, item_ids: list[str]) -> dict[str, ItemLocation]:
        by_id = {i.item_id: i.location for i in self.items}
        return {i: by_id[i] for i in item_ids if i in by_id}

    def keyword_search(
        self,
        tokens: list[str],
        prompts: list[str] | None,
        limit: int,
        models: list[str] | None = None,
        paths: list[str] | None = None,
        offset: int = 0,
    ) -> list[tuple[str, str, ItemLocation]]:
        if not tokens:
            return []
        wanted = set(prompts) if prompts else None
        rows: list[tuple[str, str, ItemLocation]] = []
        for item in self.items:
            if paths and not matches_path(item.location.source_path, paths):
                continue
            if models and item.location.model_id not in models:
                continue
            text = item.text.lower()
            if not all(tok in text for tok in tokens):
                continue
            if wanted is not None and item.location.prompt_name not in wanted:
                continue
            rows.append((item.item_id, item.text, item.location))
        rows.sort(
            key=lambda row: (row[2].paper_name or "", row[2].chunk_seq or 0, row[0])
        )
        return rows[offset : offset + limit]

    def list_prompts(self) -> list[str]:
        return sorted(
            {i.location.prompt_name for i in self.items if i.location.prompt_name}
        )

    def list_models(self) -> list[str]:
        return sorted({i.location.model_id for i in self.items if i.location.model_id})

    def list_paths(self) -> list[str]:
        return parent_paths(
            [i.location.source_path for i in self.items if i.location.source_path]
        )

    def paper_ids_for_paths(self, paths: list[str]) -> list[str]:
        return sorted(
            {
                i.location.paper_id
                for i in self.items
                if i.location.paper_id and matches_path(i.location.source_path, paths)
            }
        )
