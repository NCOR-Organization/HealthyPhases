"""Wiring for chunking."""

from __future__ import annotations

from phases_v2.chunking.adapters.secondary.DatasetChunkStore import DatasetChunkStore
from phases_v2.chunking.adapters.secondary.ObjectStorageTextSource import (
    ObjectStorageTextSource,
)
from phases_v2.chunking.adapters.secondary.WindowChunker import WindowChunker
from phases_v2.chunking.chunkers import DECLARED_CHUNKERS, WINDOW_512_128, Chunker
from phases_v2.chunking.domain import chunk_papers
from phases_v2.chunking.interfaces import ChunkReport
from phases_v2.datasets.row_store import DatasetRowStore


def mechanism_for(chunker: Chunker) -> WindowChunker:
    """Build the mechanism a declared chunker describes."""
    if chunker.name == "window":
        return WindowChunker(
            size=chunker.params["size"], overlap=chunker.params["overlap"]
        )
    raise ValueError(f"no mechanism is implemented for chunker {chunker.name!r}")


def resolve_chunker(chunker_id: str) -> Chunker:
    for chunker in DECLARED_CHUNKERS:
        if chunker.chunker_id == chunker_id:
            return chunker
    raise ValueError(
        f"{chunker_id!r} is not a declared chunker; declared chunkers are "
        + ", ".join(c.chunker_id for c in DECLARED_CHUNKERS)
    )


def chunk_corpus(
    engine,
    chunker: Chunker = WINDOW_512_128,
    paper_ids: list[str] | None = None,
) -> ChunkReport:
    return chunk_papers(
        chunker_id=chunker.chunker_id,
        mechanism=mechanism_for(chunker),
        texts=ObjectStorageTextSource(engine.services.object_storage),
        chunks=DatasetChunkStore(DatasetRowStore(engine.services.dataset)),
        paper_ids=paper_ids,
    )
