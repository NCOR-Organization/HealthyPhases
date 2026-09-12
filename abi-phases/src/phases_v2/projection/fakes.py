"""In-memory doubles for the projection domain tests."""

from __future__ import annotations

from typing import Any


class FakeTripleSink:
    """A triple store as a set per graph — RDF semantics, which is the point."""

    def __init__(self) -> None:
        self.graphs: dict[str, set[tuple]] = {}
        self.inserts = 0

    def insert(self, graph_uri: str, triples: list[tuple]) -> None:
        self.inserts += 1
        self.graphs.setdefault(graph_uri, set()).update(triples)

    def count(self, graph_uri: str) -> int:
        return len(self.graphs.get(graph_uri, set()))


class FakeProjectionLedger:
    def __init__(self) -> None:
        self.keys: dict[str, set[str]] = {}

    def projected_keys(self, target: str) -> set[str]:
        return set(self.keys.get(target, set()))

    def record(self, target: str, keys: list[str]) -> None:
        self.keys.setdefault(target, set()).update(keys)


class FakeExtractionReader:
    """Reads from lists, and can be frozen to simulate a pinned snapshot."""

    def __init__(
        self, papers=None, chunks=None, extractions=None, items=None, prompts=None
    ):
        self._prompts = list(prompts or [])
        self._papers = list(papers or [])
        self._chunks = list(chunks or [])
        self._extractions = list(extractions or [])
        self._items = list(items or [])

    def add_extraction(self, extraction: dict[str, Any], items=None) -> None:
        self._extractions.append(extraction)
        self._items.extend(items or [])

    def prompts(self):
        return list(self._prompts)

    def papers(self):
        return list(self._papers)

    def chunks(self):
        return list(self._chunks)

    def succeeded_extractions(self):
        return list(self._extractions)

    def items_for(self, extraction_ids):
        wanted = set(extraction_ids)
        return [item for item in self._items if item["extraction_id"] in wanted]


class FakeEmbedder:
    """Deterministic pseudo-embeddings, and a count of how many were computed."""

    def __init__(self, dimension: int = 4):
        self._dimension = dimension
        self.embedded: list[str] = []

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embedded.extend(texts)
        return [
            [float(len(text) + i) for i in range(self._dimension)] for text in texts
        ]


class FakeVectorSink:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, Any]] = {}

    def ensure_collection(self, name: str, dimension: int) -> None:
        self.collections.setdefault(name, {})

    def store(self, name, docs, vectors) -> None:
        target = self.collections.setdefault(name, {})
        for doc, vector in zip(docs, vectors):
            target[doc.id] = (doc, vector)

    def count(self, name: str) -> int:
        return len(self.collections.get(name, {}))
