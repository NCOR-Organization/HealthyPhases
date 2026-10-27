"""Collections of papers, using the pipeline's existing row-store port.

Collections are stored in ``paper_collections``. Rows first stored in
``input_collections`` (storage folders only) are read as collections of folder
members, so they keep listing, editing and running; the first change writes
one to ``paper_collections`` under the same id, which takes precedence from
then on. Nothing is ever deleted: archiving is a flag.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from google.protobuf.json_format import MessageToDict

from phases_v2.app.contracts.app_validation import validate_command
from phases_v2.app.pipeline_management import ManagementUnavailable
from phases_v2.paper_collections.domain import (
    add_members,
    folder_member,
    folders,
    legacy_members,
    member_from_command,
    resolve,
)
from phases_v2.paper_collections.interfaces import (
    FOLDER,
    CollectionCatalog,
    MemberUnavailable,
    Resolution,
    ResolvedPaper,
)
from phases_v2.ports import RowStore
from phases_v2.sql import literal

MAX_MEMBERS = 500
#: Papers listed on a collection's page; counts always cover all of them.
DETAIL_PAPER_LIMIT = 1000


class ResourceNotFound(KeyError):
    pass


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return value or None


def paper_status(paper: ResolvedPaper, states: dict[str, dict[str, Any]]) -> str:
    state = states.get(paper.paper_id or "")
    if state is None:
        return "not_ingested"
    return "results" if state["results"] else "ingested"


class _Memo:
    """Each source read once per call, however many collections share it."""

    def __init__(self, sources: CollectionCatalog):
        self._sources = sources
        self._cache: dict[tuple[str, str], Any] = {}

    def __getattr__(self, name: str) -> Callable[..., Any]:
        method = getattr(self._sources, name)

        def call(*args):
            key = (name, json.dumps(args, sort_keys=True, default=str))
            if key not in self._cache:
                self._cache[key] = method(*args)
            return self._cache[key]

        return call


class AppResources:
    def __init__(
        self,
        rows: RowStore | None,
        papers_root: str,
        sources: CollectionCatalog | None = None,
        supported: Callable[[str], bool] | None = None,
    ):
        self._rows = rows
        self._root = papers_root.strip("/")
        self._sources = sources
        #: Whether a file name is a document a run can read.
        self._supported = supported

    def _writable(self) -> RowStore:
        if self._rows is None:
            raise ManagementUnavailable(
                "Resource storage is unavailable in this deployment."
            )
        return self._rows

    def _catalog(self) -> CollectionCatalog:
        if self._sources is None:
            raise ManagementUnavailable(
                "Collection contents are unavailable in this deployment."
            )
        return self._sources

    # -- reading --------------------------------------------------------

    def _all(self) -> dict[str, dict[str, Any]]:
        if self._rows is None:
            return {}
        found = {
            row["collection_id"]: {
                "collection_id": row["collection_id"],
                "name": row["name"],
                "description": "",
                "members": legacy_members(_json(row["locations"]) or []),
                "archived": bool(row["archived"]),
                "created_at": None,
                "updated_at": None,
            }
            for row in self._rows.query("SELECT * FROM input_collections")
        }
        for row in self._rows.query("SELECT * FROM paper_collections"):
            found[row["collection_id"]] = dict(
                row,
                description=row["description"] or "",
                members=_json(row["members"]) or [],
                archived=bool(row["archived"]),
            )
        return found

    @staticmethod
    def _view(collection: dict[str, Any]) -> dict[str, Any]:
        return dict(
            collection,
            created_at=_iso(collection["created_at"]),
            updated_at=_iso(collection["updated_at"]),
            member_count=len(collection["members"]),
            # Storage folders, as collections first exposed them.
            locations=folders(collection["members"]),
        )

    def collections(self, include_archived: bool = False) -> list[dict[str, Any]]:
        return sorted(
            (
                self._view(c)
                for c in self._all().values()
                if include_archived or not c["archived"]
            ),
            key=lambda c: (c["name"].casefold(), c["collection_id"]),
        )

    def collection(self, collection_id: str) -> dict[str, Any]:
        found = self._all().get(collection_id)
        if found is None or found["archived"]:
            raise ResourceNotFound("Collection not found. It may have been archived.")
        return self._view(found)

    def summaries(self, counts: bool = True) -> list[dict[str, Any]]:
        """Every collection; with ``counts``, how many papers each resolves to."""
        listed = self.collections()
        if not counts or self._sources is None:
            return listed
        sources = _Memo(self._sources)
        for collection in listed:
            resolution = resolve(collection["members"], sources, self._supported)
            collection["paper_count"] = len(resolution.papers)
            collection["failed_members"] = len(resolution.failed)
        return listed

    def resolve(self, collection: dict[str, Any]) -> Resolution:
        return resolve(collection["members"], self._catalog(), self._supported)

    def paper_ids(self, collection_id: str) -> list[str]:
        """The ids of the papers a collection holds, to scope a search.

        Refuses when a member cannot be read, rather than search part of it.
        """
        resolution = self.resolve(self.collection(collection_id))
        if resolution.failed:
            raise ValueError(
                "Some members of this collection could not be read: "
                + "; ".join(resolution.failed.values())
            )
        return resolution.paper_ids()

    def detail(
        self, collection_id: str, limit: int = DETAIL_PAPER_LIMIT
    ) -> dict[str, Any]:
        """A collection with its members and the papers they resolve to now."""
        collection = self.collection(collection_id)
        sources = _Memo(self._catalog())
        resolution = resolve(collection["members"], sources, self._supported)
        labels = sources.labels(collection["members"])
        states = sources.paper_states(resolution.paper_ids())
        members = [
            dict(
                member,
                label=labels.get(member["member_id"], ""),
                paper_count=resolution.member_counts.get(member["member_id"], 0),
                error=resolution.failed.get(member["member_id"]),
            )
            for member in collection["members"]
        ]
        papers = sorted(
            resolution.papers,
            key=lambda p: (
                (p.artifact.name or p.artifact.file_name).casefold(),
                p.artifact.path,
            ),
        )
        statuses = [paper_status(p, states) for p in papers]
        return dict(
            collection,
            members=members,
            paper_count=len(papers),
            failed_members=len(resolution.failed),
            unsupported=resolution.unsupported,
            status_counts={
                status: statuses.count(status)
                for status in ("not_ingested", "ingested", "results")
            },
            truncated=len(papers) > limit,
            papers=[
                {
                    "paper_id": paper.paper_id,
                    "name": paper.artifact.name or paper.artifact.file_name,
                    "pmid": paper.artifact.pmid,
                    "path": paper.artifact.path,
                    "status": status,
                    "results": states.get(paper.paper_id or "", {}).get("results", 0),
                    "member_ids": paper.member_ids,
                }
                for paper, status in list(zip(papers, statuses, strict=True))[:limit]
            ],
        )

    # -- changing -------------------------------------------------------

    def create_collection(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = self._writable()
        command = validate_command("CreateCollection", payload)
        now = datetime.now(UTC)
        members = add_members(
            [],
            [
                *legacy_members(self._folder(loc) for loc in command.locations),
                *self._members(self._commands(command), now),
            ],
        )
        self._limit(members)
        row = {
            "collection_id": str(uuid.uuid4()),
            "name": command.name.strip(),
            "description": command.description.strip(),
            "members": members,
            "archived": False,
            "created_at": now,
            "updated_at": now,
        }
        rows.write_rows("paper_collections", [row])
        return self._view(row)

    def update_collection(
        self, collection_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self._writable()
        command = validate_command("UpdateCollection", payload)
        current = self.collection(collection_id)
        name = command.name.strip()
        if self.upload_folder(collection_id) in current["locations"]:
            self._name_upload_folder(collection_id, name)
        return self._save(current, name=name, description=command.description.strip())

    def add_members(
        self, collection_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self._writable()
        command = validate_command("AddCollectionMembers", payload)
        self.collection(collection_id)
        added = self._members(self._commands(command), datetime.now(UTC))
        # Checking members reads storage and PubMed; re-read the collection only
        # now, so a change saved meanwhile is kept rather than overwritten.
        current = self.collection(collection_id)
        members = add_members(current["members"], added)
        self._limit(members)
        return self._save(current, members=members)

    def remove_member(self, collection_id: str, member_id: str) -> dict[str, Any]:
        self._writable()
        current = self.collection(collection_id)
        kept = [m for m in current["members"] if m["member_id"] != member_id]
        if len(kept) == len(current["members"]):
            raise ResourceNotFound("That member is no longer in this collection.")
        return self._save(current, members=kept)

    def archive_collection(self, collection_id: str) -> None:
        self._writable()
        self._save(self.collection(collection_id), archived=True)

    def upload_folder(self, collection_id: str) -> str:
        """Where PDFs uploaded into the collection are stored."""
        self.collection(collection_id)
        return f"{self._root}/collections/{collection_id}"

    def add_upload_folder(self, collection_id: str) -> dict[str, Any]:
        """Make the upload folder a member, and name it in the folder lists."""
        self._writable()
        current = self.collection(collection_id)
        prefix = self.upload_folder(collection_id)
        if prefix in current["locations"]:
            return current
        now = datetime.now(UTC)
        self._name_upload_folder(collection_id, current["name"], now)
        member = folder_member(prefix, uploads=True, added_at=now)
        return self._save(current, members=add_members(current["members"], [member]))

    # -- helpers --------------------------------------------------------

    def _name_upload_folder(
        self, collection_id: str, name: str, created_at: datetime | None = None
    ) -> None:
        """Name the upload folder after the collection, in the folder lists."""
        prefix = self.upload_folder(collection_id)
        if created_at is None:
            existing = self._writable().query(
                f"SELECT created_at FROM input_locations WHERE prefix = {literal(prefix)}"
            )
            created_at = existing[0]["created_at"] if existing else datetime.now(UTC)
        suffix = " uploads"
        self._writable().write_rows(
            "input_locations",
            [
                {
                    "prefix": prefix,
                    # Folder names are at most 100 characters, as when created.
                    "name": name[: 100 - len(suffix)] + suffix,
                    "created_at": created_at,
                }
            ],
        )

    def _save(self, current: dict[str, Any], **changes: Any) -> dict[str, Any]:
        row = {
            key: current[key]
            for key in (
                "collection_id",
                "name",
                "description",
                "members",
                "archived",
                "created_at",
            )
        }
        row.update(changes, updated_at=datetime.now(UTC))
        self._writable().write_rows("paper_collections", [row])
        return self._view(row)

    @staticmethod
    def _commands(command) -> list[dict[str, Any]]:
        return MessageToDict(command, preserving_proto_field_name=True).get(
            "members", []
        )

    def _members(
        self, commands: list[dict[str, Any]], now: datetime
    ) -> list[dict[str, Any]]:
        """Stored members for validated commands, each checked to exist."""
        members = []
        for command in commands:
            if "folder" in command:
                command = {
                    "folder": {"prefix": self._folder(command["folder"]["prefix"])}
                }
            member = member_from_command(command, now)
            try:
                self._check(member)
            except MemberUnavailable as unavailable:
                raise ManagementUnavailable(str(unavailable)) from unavailable
            members.append(member)
        return members

    def _check(self, member: dict[str, Any]) -> None:
        if member["kind"] == FOLDER:
            # An empty folder is a valid member: PDFs can be added to it later.
            return
        catalog = self._catalog()
        if member.get("query_id"):
            if not catalog.pubmed_query_exists(member["query_id"]):
                raise ValueError("That PubMed search no longer exists.")
        elif member.get("pmid"):
            if not catalog.pubmed_paper(member["pmid"]):
                raise ValueError(
                    f"PMID {member['pmid']} has no downloaded PDF yet. "
                    "Download it from the Library first."
                )
        elif catalog.ingested_paper(member["paper_id"]) is None:
            raise ValueError("That paper has not been ingested, so it cannot be added.")

    def _folder(self, location: str) -> str:
        location = location.strip().rstrip("/")
        if (
            not (location == self._root or location.startswith(self._root + "/"))
            or any(part in (".", "..", "") for part in location.split("/"))
            or any(ord(c) < 32 for c in location)
            or "\\" in location
        ):
            raise ValueError(f"Folders must be inside {self._root}.")
        return location

    @staticmethod
    def _limit(members: list[dict[str, Any]]) -> None:
        if len(members) > MAX_MEMBERS:
            raise ValueError(
                f"A collection can hold at most {MAX_MEMBERS} members. "
                "Add a folder or a PubMed search instead of single papers."
            )
