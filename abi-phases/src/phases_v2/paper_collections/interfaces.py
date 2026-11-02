"""What a collection is made of, and what resolving one needs.

The domain never imports an adapter: it reads a member's documents through
:class:`MemberSources`, which says what it needs without naming object storage
or the PubMed datasets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

FOLDER = "folder"
PUBMED_QUERY = "pubmed_query"
PAPER = "paper"


class MemberUnavailable(Exception):
    """A member's documents could not be read right now. Raised by sources."""


@dataclass(frozen=True)
class Artifact:
    """One stored document. ``storage_key`` is relative to ``storage_prefix``."""

    storage_prefix: str
    storage_key: str
    #: Known for published PubMed PDFs, uploads and anything ingested before;
    #: unknown for a folder document nothing has read yet.
    content_sha256: str | None = None
    name: str = ""
    artifact_id: str | None = None
    pmid: str | None = None

    @property
    def path(self) -> str:
        return f"{self.storage_prefix.rstrip('/')}/{self.storage_key.lstrip('/')}"

    @property
    def file_name(self) -> str:
        return self.storage_key.rsplit("/", 1)[-1]


@dataclass
class ResolvedPaper:
    artifact: Artifact
    #: Every member that contributed this document, in member order.
    member_ids: list[str] = field(default_factory=list)

    @property
    def paper_id(self) -> str | None:
        # A paper's identity is its content, so a known checksum is its id.
        return self.artifact.content_sha256


@dataclass
class Resolution:
    """A collection as an exact list of documents, one per distinct content."""

    papers: list[ResolvedPaper] = field(default_factory=list)
    #: Distinct documents each member resolves to.
    member_counts: dict[str, int] = field(default_factory=dict)
    #: Members that could not be read, with the reason.
    failed: dict[str, str] = field(default_factory=dict)
    #: Folder objects no renderer handles, so not papers.
    unsupported: int = 0

    def paper_ids(self) -> list[str]:
        return [p.paper_id for p in self.papers if p.paper_id]

    def manifest(self) -> list[dict[str, Any]]:
        """The artifacts a run reads, in the shape ``source_manifests`` keeps."""
        return [
            {
                "storage_prefix": p.artifact.storage_prefix,
                "storage_key": p.artifact.storage_key,
                "content_sha256": p.artifact.content_sha256 or "",
                "artifact_id": p.artifact.artifact_id or "",
            }
            for p in self.papers
        ]


class MemberSources(Protocol):
    def folder(self, prefix: str) -> list[Artifact]:
        """Every object at or beneath ``prefix``; empty if it does not exist."""
        ...

    def pubmed_query(self, query_id: str) -> list[Artifact]:
        """The saved search's currently published PDFs."""
        ...

    def pubmed_paper(self, pmid: str) -> list[Artifact]:
        """The paper's currently published PDFs."""
        ...

    def ingested_paper(self, paper_id: str) -> Artifact | None:
        """Where an ingested paper is stored, or None if it is not ingested."""
        ...

    def paper_ids_by_path(self, paths: list[str]) -> dict[str, str]:
        """Ingested papers among ``paths`` (``prefix/key``), mapped to their ids."""
        ...


class CollectionCatalog(MemberSources, Protocol):
    """What the collection pages need beyond resolution: names and states."""

    def pubmed_query_exists(self, query_id: str) -> bool: ...

    def labels(self, members: list[dict[str, Any]]) -> dict[str, str]:
        """A readable name for each member, by member id."""
        ...

    def paper_states(self, paper_ids: list[str]) -> dict[str, dict[str, Any]]:
        """``{"ingested": bool, "results": int}`` for each id that is known."""
        ...
