"""In-memory doubles for the extraction domain tests."""

from __future__ import annotations

import json

from phases_v2.extraction.interfaces import (
    ChunkRef,
    ExtractedItemRecord,
    ExtractionRecord,
    ModelFailed,
    RunRecord,
    SUCCEEDED,
)


class FakeModel:
    """Returns a canned response, or fails, per prompt."""

    def __init__(self, response: str | None = None, fail_on: set[str] | None = None):
        self._response = (
            response if response is not None else json.dumps({"results": ["a claim"]})
        )
        self._fail_on = fail_on or set()
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        for marker in self._fail_on:
            if marker in prompt:
                raise ModelFailed(f"model refused: {marker}")
        return self._response


class FakeExtractionStore:
    def __init__(self, chunks: list[ChunkRef] | None = None):
        self._chunks = list(chunks or [])
        self.extractions: dict[str, ExtractionRecord] = {}
        self.items: dict[str, ExtractedItemRecord] = {}
        self.runs: dict[str, RunRecord] = {}
        self.write_order: list[str] = []

    def add_chunk(self, chunk: ChunkRef) -> None:
        self._chunks.append(chunk)

    def outstanding_chunks(
        self,
        *,
        chunker_id: str,
        model_id: str,
        prompt_id: str,
        paper_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> list[ChunkRef]:
        done = {
            record.chunk_id
            for record in self.extractions.values()
            if record.model_id == model_id
            and record.prompt_id == prompt_id
            and record.status == SUCCEEDED
        }
        found = [
            chunk
            for chunk in self._chunks
            if chunk.chunk_id not in done
            and (paper_ids is None or chunk.paper_id in paper_ids)
        ]
        return found[:limit] if limit is not None else found

    def count_candidates(
        self, *, chunker_id: str, paper_ids: list[str] | None = None
    ) -> int:
        return len(
            [
                chunk
                for chunk in self._chunks
                if paper_ids is None or chunk.paper_id in paper_ids
            ]
        )

    def save_items(self, items: list[ExtractedItemRecord]) -> None:
        self.write_order.append("items")
        for item in items:
            self.items[item.item_id] = item

    def save_extractions(self, extractions: list[ExtractionRecord]) -> None:
        self.write_order.append("extractions")
        for record in extractions:
            self.extractions[record.extraction_id] = record

    def save_run(self, run: RunRecord) -> None:
        self.write_order.append("run")
        self.runs[run.run_id] = run
