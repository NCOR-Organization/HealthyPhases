"""What trying a prompt needs, stated without naming a technology.

Every method here reads. Trying a prompt must leave no trace in the datasets,
so the port offers no way to write one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from phases_v2.extraction.interfaces import ExtractionModel
from phases_v2.prompts.domain import PromptTemplate

#: Builds the model for one declared model id, bound to one output key.
ModelFactory = Callable[[str, str], ExtractionModel]

TIMED_OUT = "timed_out"
NOT_RUN = "not_run"


@dataclass(frozen=True)
class PaperChunk:
    seq: int
    chunk_id: str
    paper_id: str
    text: str


@dataclass(frozen=True)
class StoredExtraction:
    """What a pipeline run already recorded for one chunk, model and prompt."""

    status: str
    error: str | None
    items: list[str]


@dataclass
class BaselineChunk:
    status: str
    items: list[Any] = field(default_factory=list)
    error: str | None = None


@dataclass
class ChunkTry:
    seq: int
    chunk_id: str
    text: str
    status: str
    items: list[Any]
    error: str | None
    #: The model's answer verbatim, kept only when it could not be used.
    raw_output: str | None
    elapsed_ms: int
    baseline: BaselineChunk | None = None


@dataclass
class TryReport:
    prompt_id: str
    name: str
    output_key: str
    #: Whether this exact text is already a version in the library.
    saved: bool
    model_id: str
    paper_id: str
    chunker_id: str
    baseline_prompt_id: str | None
    baseline_output_key: str | None
    chunks: list[ChunkTry]
    elapsed_ms: int
    timed_out: bool


class PlaygroundStore(Protocol):
    def prompt(self, prompt_id: str) -> PromptTemplate | None:
        """A saved or declared version, or ``None`` when there is no such id."""
        ...

    def is_ingested(self, paper_id: str) -> bool:
        """Whether the paper exists and its text has been extracted."""
        ...

    def chunk_counts(self, paper_id: str) -> dict[str, int]:
        """How many chunks the paper has, per chunker it was cut with."""
        ...

    def chunks(
        self,
        paper_id: str,
        chunker_id: str,
        *,
        seqs: list[int] | None = None,
        first: int | None = None,
    ) -> list[PaperChunk]:
        """The chunks at ``seqs``, or the first ``first`` chunks, in seq order."""
        ...

    def stored(
        self, chunk_ids: list[str], *, model_id: str, prompt_id: str
    ) -> dict[str, StoredExtraction]:
        """Recorded extractions for these chunks, keyed by chunk id."""
        ...
