"""What an ingestion coverage report reads, and what it says.

The domain asks :class:`CoverageReader` for everything. The reader is pinned to
one dataset snapshot, so every number in a report is read at the same instant,
and it has no method that writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from phases_v2.paper_collections.interfaces import Artifact, MemberSources

DEFAULT_MODEL = "openai/gpt-4.1-mini"

# Kinds of source.
COLLECTION = "collection"
PUBMED_SEARCH = "pubmed_search"
EVERYTHING = "everything"

# What happened to one chunk for one prompt version and model.
SUCCEEDED = "succeeded"
#: The call failed and no answer is stored (a dropped connection, a timeout).
FAILED_CALL = "failed_call"
#: An answer is stored in ``raw_response``, but it was not valid for the prompt.
INVALID_ANSWER = "invalid_answer"
NOT_RUN = "not_run"
STATES = (SUCCEEDED, FAILED_CALL, INVALID_ANSWER, NOT_RUN)

# Projection targets, as the projectors' ledger names them.
GRAPH = "graph"
VECTOR_CHUNKS = "vector_chunks"
VECTOR_ITEMS = "vector_items"
RELATIONS = "probabilistic_relations_v1"
TARGETS = (GRAPH, VECTOR_CHUNKS, VECTOR_ITEMS, RELATIONS)


@dataclass(frozen=True)
class Selection:
    """The prompt versions, models and chunker a report checks."""

    models: tuple[str, ...]
    prompt_ids: tuple[str, ...]
    chunker_id: str


@dataclass(frozen=True)
class Collection:
    collection_id: str
    name: str
    members: list[dict[str, Any]]


@dataclass(frozen=True)
class SavedSearch:
    query_id: str
    query: str


@dataclass(frozen=True)
class PromptVersion:
    prompt_id: str
    #: None when extractions name a prompt id that ``prompts`` does not hold.
    name: str | None
    extractions: int = 0
    succeeded: int = 0


@dataclass(frozen=True)
class CoverageCount:
    """Chunks of one scope in one state, for one prompt version and model."""

    scope: str
    model_id: str
    prompt_id: str
    state: str
    #: The stored error, for failed chunks; None otherwise.
    reason: str | None
    chunks: int


@dataclass(frozen=True)
class FailureCount:
    """Failed extractions of one prompt version and model, by reason."""

    prompt_id: str
    model_id: str
    state: str
    reason: str
    count: int


@dataclass(frozen=True)
class Backlog:
    """Keys a projector has not projected yet, overall and within the selection."""

    target: str
    outstanding: int
    selected: int


@dataclass(frozen=True)
class RelationCheck:
    """What the relations projector would do with its outstanding items now.

    It never records an item it rejects, so a rejected item stays outstanding
    however often the projection runs.
    """

    examined: int
    rejected: int
    #: Rejected items of the selected prompts, models and chunker.
    rejected_selected: int = 0
    #: Item id → why it is rejected, for the first few.
    sample_errors: dict[str, str] = field(default_factory=dict)


class CoverageReader(Protocol):
    def snapshot(self) -> int | None:
        """The dataset snapshot every other method reads."""
        ...

    def collections(self) -> list[Collection]:
        """Every collection that is not archived, legacy ones included."""
        ...

    def saved_searches(self) -> list[SavedSearch]:
        """Every saved PubMed search with at least one downloaded PDF."""
        ...

    def member_sources(self) -> MemberSources:
        """What collection members and saved searches resolve through.

        Folder documents nothing has ingested are identified by their content,
        like every other document.
        """
        ...

    def supported(self, file_name: str) -> bool:
        """Whether a run can read a file with this name."""
        ...

    def downloaded_pdfs(self) -> list[Artifact]:
        """Every PDF the PubMed library holds, searched for or not."""
        ...

    def ingested_papers(self) -> list[Artifact]:
        """Every ingested paper, where it was first read from."""
        ...

    def chunked_papers(self, chunker_id: str) -> set[str]:
        """Ids of the papers that have chunks cut with ``chunker_id``."""
        ...

    def coverage(
        self, scopes: dict[str, list[str]], selection: Selection
    ) -> list[CoverageCount]:
        """Each scope's chunks, by state and reason, per selected prompt and model.

        ``scopes`` maps a scope key to paper ids. A chunk with no extraction for
        a prompt version and model counts as not run.
        """
        ...

    def failures(self) -> list[FailureCount]:
        """Every failed extraction, of any prompt version and model, by reason."""
        ...

    def prompt_versions(self) -> list[PromptVersion]:
        """Every stored prompt version, and how many extractions each has."""
        ...

    def run_requests(self) -> list[dict[str, Any]]:
        """Every run request, newest first."""
        ...

    def projection_backlog(self, selection: Selection) -> list[Backlog]:
        """One row per target of :data:`TARGETS`."""
        ...

    def relation_check(self, selection: Selection) -> RelationCheck:
        """Every outstanding relation item, checked as the projector checks it."""
        ...
