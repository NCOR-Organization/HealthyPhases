"""What extraction needs, stated without naming a model vendor or a store."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

SUCCEEDED = "succeeded"
FAILED = "failed"


class ModelFailed(Exception):
    """The model could not be called, or returned something unusable."""

    def __init__(self, message: str, *, raw_response: str | None = None):
        super().__init__(message)
        self.raw_response = raw_response


@dataclass(frozen=True)
class ChunkRef:
    chunk_id: str
    paper_id: str
    text: str


@dataclass(frozen=True)
class ExtractionRecord:
    extraction_id: str
    chunk_id: str
    model_id: str
    prompt_id: str
    run_id: str
    status: str
    response: Any
    raw_response: str | None
    error: str | None
    item_count: int
    completed_at: datetime


@dataclass(frozen=True)
class ExtractedItemRecord:
    item_id: str
    extraction_id: str
    chunk_id: str
    paper_id: str
    prompt_id: str
    seq: int
    text: str


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    chunker_id: str
    model_id: str
    prompt_id: str
    started_at: datetime
    finished_at: datetime
    succeeded: int
    failed: int
    skipped: int


@dataclass
class ExtractionReport:
    run_id: str = ""
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def executed(self) -> int:
        return self.succeeded + self.failed


class ExtractionModel(Protocol):
    def complete(self, prompt: str) -> str:
        """Send ``prompt`` and return the model's raw response.

        Raises :class:`ModelFailed` for anything that stops one unit of work,
        so a single bad call is recorded and the run continues.
        """
        ...


class ExtractionStore(Protocol):
    def outstanding_chunks(
        self,
        *,
        chunker_id: str,
        model_id: str,
        prompt_id: str,
        paper_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> list[ChunkRef]:
        """Chunks with no succeeded extraction for this model and prompt.

        A failed attempt is outstanding again: it is absent from the join, so
        it comes back on the next run.
        """
        ...

    def count_candidates(
        self, *, chunker_id: str, paper_ids: list[str] | None = None
    ) -> int:
        """How many chunks the run is scoped to in total, done or not."""
        ...

    def save_items(self, items: list[ExtractedItemRecord]) -> None: ...

    def save_extractions(self, extractions: list[ExtractionRecord]) -> None: ...

    def save_run(self, run: RunRecord) -> None: ...
