"""What chunking needs, stated without naming a technology."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PaperText:
    paper_id: str
    text_key: str


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    paper_id: str
    chunker_id: str
    seq: int
    text: str
    char_start: int
    char_end: int
    token_count: int


@dataclass
class ChunkReport:
    papers_considered: int = 0
    papers_chunked: int = 0
    papers_skipped: int = 0
    chunks_written: int = 0


class ChunkingMechanism(Protocol):
    """Splits a paper's text into the units extraction runs against."""

    def split(self, text: str) -> list[tuple[str, int, int]]:
        """Return ``(text, char_start, char_end)`` per chunk, in order.

        Offsets are into the text given, so a chunk can always be located in
        the source it came from.
        """
        ...


class TextSource(Protocol):
    def read_text(self, text_key: str) -> str: ...


class ChunkStore(Protocol):
    def outstanding_papers(
        self, chunker_id: str, paper_ids: list[str] | None = None
    ) -> list[PaperText]:
        """Papers with rendered text that this chunker has not chunked yet."""
        ...

    def save(self, chunks: list[ChunkRecord]) -> None: ...
