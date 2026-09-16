"""What the projectors need, stated without naming a store."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

GRAPH = "graph"
VECTOR_CHUNKS = "vector_chunks"
VECTOR_ITEMS = "vector_items"


@dataclass
class ProjectionReport:
    projected: int = 0
    already_projected: int = 0


class TripleSink(Protocol):
    def insert(self, graph_uri: str, triples: list[tuple]) -> None:
        """Add ``triples`` to the named graph. Re-adding one is a no-op."""
        ...


class ProjectionLedger(Protocol):
    def projected_keys(self, target: str) -> set[str]:
        """Keys already projected to ``target``."""
        ...

    def record(self, target: str, keys: list[str]) -> None: ...


class ExtractionReader(Protocol):
    def prompts(self) -> list[dict[str, Any]]: ...

    def papers(self) -> list[dict[str, Any]]: ...

    def chunks(self) -> list[dict[str, Any]]: ...

    def succeeded_extractions(self) -> list[dict[str, Any]]: ...

    def items_for(self, extraction_ids: list[str]) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class VectorDoc:
    """One embeddable row, with the provenance a search hit needs."""

    id: str
    text: str
    metadata: dict[str, Any]


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[Any]:
        """One vector per text, in order."""
        ...

    @property
    def dimension(self) -> int: ...


class VectorSink(Protocol):
    def ensure_collection(self, name: str, dimension: int) -> None: ...

    def store(self, name: str, docs: list[VectorDoc], vectors: list[Any]) -> None:
        """Upsert by id, so re-storing a doc replaces rather than duplicates."""
        ...
