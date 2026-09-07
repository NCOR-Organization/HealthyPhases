"""In-memory doubles for the chunking domain tests."""

from __future__ import annotations

from phases_v2.chunking.interfaces import ChunkRecord, PaperText


class FakeTextSource:
    def __init__(self, texts: dict[str, str] | None = None):
        self._texts = dict(texts or {})
        self.reads: list[str] = []

    def add(self, text_key: str, text: str) -> None:
        self._texts[text_key] = text

    def read_text(self, text_key: str) -> str:
        self.reads.append(text_key)
        return self._texts[text_key]


class FakeChunkStore:
    def __init__(self, papers: list[PaperText] | None = None):
        self._papers = list(papers or [])
        self.chunks: dict[str, ChunkRecord] = {}
        self.reads = 0

    def add_paper(self, paper: PaperText) -> None:
        self._papers.append(paper)

    def outstanding_papers(
        self, chunker_id: str, paper_ids: list[str] | None = None
    ) -> list[PaperText]:
        self.reads += 1
        chunked = {
            chunk.paper_id
            for chunk in self.chunks.values()
            if chunk.chunker_id == chunker_id
        }
        return [
            paper
            for paper in self._papers
            if paper.paper_id not in chunked
            and (paper_ids is None or paper.paper_id in paper_ids)
        ]

    def save(self, chunks: list[ChunkRecord]) -> None:
        for chunk in chunks:
            self.chunks[chunk.chunk_id] = chunk
