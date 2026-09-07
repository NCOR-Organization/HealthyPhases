"""What paper ingestion needs, stated without naming a technology.

The domain never imports an adapter: it discovers objects through
:class:`ObjectSource`, turns them into text through :class:`TextRenderer`, and
records what it found through :class:`PaperStore`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


class ObjectNotFound(Exception):
    """A location does not exist. Raised by :class:`ObjectSource`."""


class RenderFailed(Exception):
    """An object could not be turned into text."""


@dataclass(frozen=True)
class DiscoveredObject:
    location: str
    key: str
    content: bytes


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    storage_prefix: str
    storage_key: str
    file_name: str
    content_sha256: str
    size_bytes: int
    mime_type: str | None
    text_key: str | None
    discovered_at: datetime


@dataclass
class IngestReport:
    """What a run did, in enough detail to explain itself afterwards."""

    discovered: int = 0
    ingested: int = 0
    skipped: int = 0
    failed_locations: dict[str, str] = field(default_factory=dict)
    failed_papers: dict[str, str] = field(default_factory=dict)

    @property
    def failed(self) -> int:
        return len(self.failed_locations) + len(self.failed_papers)


class ObjectSource(Protocol):
    def list_objects_recursive(self, prefix: str) -> list[str]:
        """Every object key at or beneath ``prefix``, at any depth.

        Raises :class:`ObjectNotFound` if the prefix does not exist.
        """
        ...

    def get_object(self, prefix: str, key: str) -> bytes: ...

    def put_object(self, prefix: str, key: str, content: bytes) -> None: ...


class TextRenderer(Protocol):
    def render(self, content: bytes, file_name: str) -> str:
        """Turn a paper's bytes into text suitable for chunking.

        Raises :class:`RenderFailed` for anything it cannot read, so one
        unreadable object does not end a run.
        """
        ...

    def handles(self, file_name: str) -> bool:
        """Whether this renderer claims the file at all."""
        ...


class PaperStore(Protocol):
    def already_ingested(self) -> dict[str, str | None]:
        """``paper_id`` to its ``text_key``, for everything recorded so far.

        One query rather than a lookup per paper: the corpus is large but this
        is two columns of hashes, and the alternative is a round trip per
        object on every re-run.
        """
        ...

    def save(self, papers: list[PaperRecord]) -> None: ...
