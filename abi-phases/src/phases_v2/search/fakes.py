"""In-memory fakes implementing the search ports.

Used by the domain tests and by the generic port-contract checks in
``contracts.py`` so any real adapter can be validated against the same
expectations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from phases_v2.search.models import ItemLocation, SemanticMatch


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

    def search(
        self, query: str, k: int, score_threshold: float | None = None
    ) -> list[SemanticMatch]:
        ranked = sorted(self.items, key=lambda i: i.similarity, reverse=True)
        out = [
            SemanticMatch(item_id=i.item_id, text=i.text, score=i.similarity)
            for i in ranked
            if score_threshold is None or i.similarity >= score_threshold
        ]
        return out[:k]


@dataclass
class FakeExtractedItems:
    items: list[FakeItem] = field(default_factory=list)

    def resolve_locations(self, item_ids: list[str]) -> dict[str, ItemLocation]:
        by_id = {i.item_id: i.location for i in self.items}
        return {i: by_id[i] for i in item_ids if i in by_id}

    def keyword_search(
        self, tokens: list[str], prompts: list[str] | None, limit: int
    ) -> list[tuple[str, str, ItemLocation]]:
        wanted = set(prompts) if prompts else None
        rows: list[tuple[str, str, ItemLocation]] = []
        for item in self.items:
            text = item.text.lower()
            if not all(tok in text for tok in tokens):
                continue
            if wanted is not None and item.location.prompt_name not in wanted:
                continue
            rows.append((item.item_id, item.text, item.location))
        return rows[:limit]

    def list_prompts(self) -> list[str]:
        return sorted(
            {i.location.prompt_name for i in self.items if i.location.prompt_name}
        )
