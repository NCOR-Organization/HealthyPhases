"""In-memory fakes implementing the search ports.

Used by the unit tests and by the generic port-contract tests so any real
adapter can be validated against the same expectations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from phases.app.interfaces import IKnowledgeGraphPort, ISemanticIndexPort
from phases.app.models import ItemLocation, SemanticMatch


@dataclass
class FakeItem:
    extracted_item_id: str
    text: str
    location: ItemLocation
    # Higher = more similar to any query, for deterministic semantic ordering.
    similarity: float = 0.5


@dataclass
class FakeSemanticIndex(ISemanticIndexPort):
    items: list[FakeItem] = field(default_factory=list)

    def search(
        self, query: str, k: int, score_threshold: float | None = None
    ) -> list[SemanticMatch]:
        ranked = sorted(self.items, key=lambda i: i.similarity, reverse=True)
        out = [
            SemanticMatch(
                extracted_item_id=i.extracted_item_id, text=i.text, score=i.similarity
            )
            for i in ranked
            if score_threshold is None or i.similarity >= score_threshold
        ]
        return out[:k]


@dataclass
class FakeKnowledgeGraph(IKnowledgeGraphPort):
    items: list[FakeItem] = field(default_factory=list)

    def resolve_locations(self, item_ids: list[str]) -> dict[str, ItemLocation]:
        by_id = {i.extracted_item_id: i.location for i in self.items}
        return {i: by_id[i] for i in item_ids if i in by_id}

    def keyword_search(
        self, tokens: list[str], pipelines: list[str] | None, limit: int
    ) -> list[tuple[str, str, ItemLocation]]:
        wanted = set(pipelines) if pipelines else None
        rows: list[tuple[str, str, ItemLocation]] = []
        for item in self.items:
            text = item.text.lower()
            if not all(tok in text for tok in tokens):
                continue
            if wanted is not None and item.location.pipeline not in wanted:
                continue
            rows.append((item.extracted_item_id, item.text, item.location))
        return rows[:limit]

    def list_pipelines(self) -> list[str]:
        return sorted(
            {i.location.pipeline for i in self.items if i.location.pipeline}
        )
