"""In-memory doubles for the playground domain tests."""

from __future__ import annotations

import threading

from phases_v2 import identity
from phases_v2.playground.interfaces import PaperChunk, StoredExtraction
from phases_v2.prompts.domain import PromptTemplate


class FakePlaygroundStore:
    """Papers, chunks, prompts and stored extractions, held in dictionaries.

    Read-only like the real adapter: there is nothing here a try could write to.
    """

    def __init__(self) -> None:
        self.prompts: dict[str, PromptTemplate] = {}
        self.ingested: set[str] = set()
        self.paper_chunks: dict[tuple[str, str], list[PaperChunk]] = {}
        self.extractions: dict[tuple[str, str, str], StoredExtraction] = {}

    def add_prompt(self, prompt: PromptTemplate) -> PromptTemplate:
        self.prompts[prompt.prompt_id] = prompt
        return prompt

    def add_paper(
        self, paper_id: str, chunker_id: str, texts: list[str]
    ) -> list[PaperChunk]:
        self.ingested.add(paper_id)
        chunks = [
            PaperChunk(
                seq=seq,
                chunk_id=identity.chunk_id(paper_id, chunker_id, seq),
                paper_id=paper_id,
                text=text,
            )
            for seq, text in enumerate(texts)
        ]
        self.paper_chunks[(paper_id, chunker_id)] = chunks
        return chunks

    def add_extraction(
        self, chunk_id: str, model_id: str, prompt_id: str, stored: StoredExtraction
    ) -> None:
        self.extractions[(chunk_id, model_id, prompt_id)] = stored

    # -- PlaygroundStore ------------------------------------------------

    def prompt(self, prompt_id: str) -> PromptTemplate | None:
        return self.prompts.get(prompt_id)

    def is_ingested(self, paper_id: str) -> bool:
        return paper_id in self.ingested

    def chunk_counts(self, paper_id: str) -> dict[str, int]:
        return {
            chunker: len(chunks)
            for (paper, chunker), chunks in self.paper_chunks.items()
            if paper == paper_id
        }

    def chunks(self, paper_id, chunker_id, *, seqs=None, first=None):
        found = self.paper_chunks.get((paper_id, chunker_id), [])
        if seqs:
            return [chunk for chunk in found if chunk.seq in seqs]
        return found[:first] if first is not None else list(found)

    def stored(self, chunk_ids, *, model_id, prompt_id):
        return {
            chunk_id: self.extractions[(chunk_id, model_id, prompt_id)]
            for chunk_id in chunk_ids
            if (chunk_id, model_id, prompt_id) in self.extractions
        }


class BlockingModel:
    """Answers only once released, to exercise the overall deadline."""

    def __init__(self, response: str):
        self._response = response
        self.release = threading.Event()
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        self.release.wait(5)
        return self._response
