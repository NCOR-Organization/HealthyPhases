"""Collections of papers, and turning one into the exact documents it holds.

A collection is a list of members, each a way of naming papers:

- ``folder``: a storage prefix, including its subfolders;
- ``pubmed_query``: a saved PubMed search. It is live: it stands for the
  search's currently published PDFs every time the collection is used;
- ``paper``: one document, either an ingested paper (``paper_id``) or a PubMed
  paper with a published PDF (``pmid``).

:func:`resolve` is the one place a collection becomes documents. Preview, run
submission and search scoping all call it, so they cannot disagree about what
a collection contains. A paper's identity is its content, so the same PDF
reached through two members, or stored at two paths, is one paper.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from typing import Any

from phases_v2.paper_collections.interfaces import (
    FOLDER,
    PAPER,
    PUBMED_QUERY,
    Artifact,
    MemberSources,
    MemberUnavailable,
    Resolution,
    ResolvedPaper,
)

_SHA256 = re.compile(r"[a-f0-9]{64}")


def member_id(kind: str, value: str) -> str:
    """A member's id follows from what it names, so adding it twice is a no-op."""
    return f"{kind}-{sha256(f'{kind}:{value}'.encode()).hexdigest()[:16]}"


def folder_member(
    prefix: str, *, uploads: bool = False, added_at: datetime | None = None
) -> dict[str, Any]:
    member: dict[str, Any] = {
        "member_id": member_id(FOLDER, prefix),
        "kind": FOLDER,
        "prefix": prefix,
    }
    if uploads:
        # The folder PDFs uploaded into the collection are stored in.
        member["uploads"] = True
    if added_at is not None:
        member["added_at"] = added_at.isoformat()
    return member


def member_from_command(
    command: dict[str, Any], added_at: datetime | None = None
) -> dict[str, Any]:
    """A stored member from a validated ``CollectionMember`` command.

    ``command`` is the command as a dict: exactly one of ``folder``,
    ``pubmed_query`` or ``paper``, as the contract enforces.
    """
    if "folder" in command:
        return folder_member(command["folder"]["prefix"], added_at=added_at)
    if "pubmed_query" in command:
        query_id = command["pubmed_query"]["query_id"]
        member = {
            "member_id": member_id(PUBMED_QUERY, query_id),
            "kind": PUBMED_QUERY,
            "query_id": query_id,
        }
    else:
        paper = command["paper"]
        field = "paper_id" if paper.get("paper_id") else "pmid"
        member = {
            "member_id": member_id(PAPER, f"{field}:{paper[field]}"),
            "kind": PAPER,
            field: paper[field],
        }
    if added_at is not None:
        member["added_at"] = added_at.isoformat()
    return member


def legacy_members(locations: Iterable[str]) -> list[dict[str, Any]]:
    """A first-form collection's storage folders, as folder members."""
    return [folder_member(prefix) for prefix in dict.fromkeys(locations)]


def add_members(
    existing: list[dict[str, Any]], new: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """``existing`` followed by each new member it does not already hold."""
    held = {m["member_id"] for m in existing}
    out = list(existing)
    for member in new:
        if member["member_id"] not in held:
            held.add(member["member_id"])
            out.append(member)
    return out


def folders(members: Iterable[dict[str, Any]]) -> list[str]:
    return [m["prefix"] for m in members if m["kind"] == FOLDER]


def resolve(
    members: list[dict[str, Any]],
    sources: MemberSources,
    supported: Callable[[str], bool] | None = None,
) -> Resolution:
    """The documents ``members`` stand for right now, one per distinct content.

    A member that cannot be read is recorded in ``failed`` and the others
    still resolve, so one unreachable folder does not hide the rest; callers
    that must be exact (run submission) refuse when anything failed.
    ``supported`` says whether a file name is a document a run can read.
    """
    resolution = Resolution()
    found: list[tuple[str, Artifact]] = []
    unsupported: set[str] = set()
    for member in members:
        mid = member["member_id"]
        resolution.member_counts[mid] = 0
        try:
            artifacts = _artifacts(member, sources)
        except MemberUnavailable as unavailable:
            resolution.failed[mid] = str(unavailable)
            continue
        for artifact in artifacts:
            if supported is not None and not supported(artifact.file_name):
                unsupported.add(artifact.path)
                continue
            found.append((mid, artifact))
    resolution.unsupported = len(unsupported)

    unknown = list(dict.fromkeys(a.path for _, a in found if not a.content_sha256))
    known = sources.paper_ids_by_path(unknown) if unknown else {}

    by_content: dict[str, ResolvedPaper] = {}
    for mid, artifact in found:
        checksum = artifact.content_sha256 or known.get(artifact.path)
        if checksum and not artifact.content_sha256:
            artifact = replace(artifact, content_sha256=checksum)
        key = checksum or f"path:{artifact.path}"
        paper = by_content.get(key)
        if paper is None:
            by_content[key] = ResolvedPaper(artifact, [mid])
        elif mid not in paper.member_ids:
            paper.member_ids.append(mid)
    resolution.papers = list(by_content.values())
    for paper in resolution.papers:
        for mid in paper.member_ids:
            resolution.member_counts[mid] += 1
    return resolution


def _artifacts(member: dict[str, Any], sources: MemberSources) -> list[Artifact]:
    kind = member["kind"]
    if kind == FOLDER:
        return _with_upload_checksums(sources.folder(member["prefix"]))
    if kind == PUBMED_QUERY:
        return sources.pubmed_query(member["query_id"])
    if kind == PAPER:
        if member.get("pmid"):
            return sources.pubmed_paper(member["pmid"])
        paper = sources.ingested_paper(member["paper_id"])
        return [paper] if paper else []
    raise ValueError(f"Unknown collection member kind: {kind}")


def _with_upload_checksums(artifacts: list[Artifact]) -> list[Artifact]:
    """Uploads are stored as ``<sha256>/<file name>``; the folder names the content.

    Only a 64-hex folder holding exactly one file is taken for an upload: one
    holding several files is something else, and guessing would merge
    different documents into one paper. Ingestion still verifies a manifest
    checksum against the bytes it reads, so a lone file in a folder that only
    looks like an upload fails loudly rather than ingesting the wrong document.
    """
    parents: dict[str, int] = {}
    for artifact in artifacts:
        parent = artifact.path.rsplit("/", 1)[0]
        parents[parent] = parents.get(parent, 0) + 1
    out = []
    for artifact in artifacts:
        parent = artifact.path.rsplit("/", 1)[0]
        name = parent.rsplit("/", 1)[-1]
        if (
            not artifact.content_sha256
            and _SHA256.fullmatch(name)
            and parents[parent] == 1
        ):
            artifact = replace(artifact, content_sha256=name)
        out.append(artifact)
    return out
