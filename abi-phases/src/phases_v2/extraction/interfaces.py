"""What extraction needs, stated without naming a model vendor or a store."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

SUCCEEDED = "succeeded"
FAILED = "failed"

# Answer keys a prompt's output used to be returned under. A prompt that was
# renamed keeps the wording its earlier extractions were made with, and that
# wording still asks for the old key, so both are accepted.
LEGACY_OUTPUT_KEYS: dict[str, tuple[str, ...]] = {
    "conditional_statement": ("logical_sentences",),
}


class ModelFailed(Exception):
    """The model could not be called, or returned something unusable.

    ``transient`` is the adapter's statement that trying the same call again
    may succeed — a dropped connection, a timeout, a rate limit, a provider
    5xx. It is never set for unusable output: asking again for a different
    answer is a decision about the prompt, not about the network.
    """

    def __init__(
        self,
        message: str,
        *,
        raw_response: str | None = None,
        transient: bool = False,
    ):
        super().__init__(message)
        self.raw_response = raw_response
        self.transient = transient


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

        Implementations must support concurrent calls from extraction workers.

        Raises :class:`ModelFailed` for anything that stops one unit of work,
        so a single bad call is recorded and the run continues. Failures worth
        retrying carry ``transient=True``; the domain does the retrying.
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
