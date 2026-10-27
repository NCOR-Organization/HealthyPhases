"""The run requests that included a paper, and the papers a request covered.

The PubMed library and OpenAlex records a paper links to are read by
:mod:`phases_v2.sources.library_links`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from phases_v2.ports import RowStore
from phases_v2.sql import in_list, literal


@dataclass(frozen=True)
class PaperFacts:
    """What decides whether a request included a paper."""

    paper_id: str
    content_sha256: str | None
    paths: frozenset[str]
    discovered_at: datetime | None
    run_ids: frozenset[str]

    @classmethod
    def of(cls, paper: dict[str, Any], paths: list[str], run_ids: list[str]):
        """``paper`` is its ``papers`` row; ``paths`` every path it was read from."""
        own = (
            [_join(paper.get("storage_prefix"), paper["storage_key"])]
            if paper.get("storage_key")
            else []
        )
        return cls(
            paper_id=paper["paper_id"],
            content_sha256=paper.get("content_sha256"),
            paths=frozenset(own + [p.strip("/") for p in paths if p]),
            discovered_at=_instant(paper.get("discovered_at")),
            run_ids=frozenset(r for r in run_ids if r),
        )


@dataclass(frozen=True)
class RequestScope:
    """The papers one request covered, stated three ways.

    A request read either exactly its manifest's artifacts or every PDF under
    its folders, and wrote extractions under its own run ids. The run ids alone
    miss the papers it skipped because they already had results, and the
    folders alone would claim papers that were added after it finished.
    """

    request_id: str
    run_ids: tuple[str, ...]
    folders: tuple[str, ...]
    hashes: frozenset[str]
    paths: frozenset[str]
    finished_at: datetime | None

    @classmethod
    def of(cls, request: dict[str, Any], manifest: list | None) -> RequestScope:
        from phases_v2.orchestrations.PhasesV2Orchestration import (
            MANIFEST_SOURCE,
            extraction_run_id,
        )

        locations = _json_list(request.get("locations"))
        artifacts = [a for a in (manifest or []) if isinstance(a, dict)]
        return cls(
            request_id=request["request_id"],
            run_ids=tuple(
                extraction_run_id(request["request_id"], prompt_id)
                for prompt_id in _json_list(request.get("prompt_ids"))
            ),
            folders=tuple(
                folder
                for location in locations
                if not str(location).startswith(MANIFEST_SOURCE)
                and (folder := str(location).strip("/"))
            ),
            hashes=frozenset(
                a["content_sha256"] for a in artifacts if a.get("content_sha256")
            ),
            paths=frozenset(
                _join(a.get("storage_prefix"), a.get("storage_key"))
                for a in artifacts
                if a.get("storage_key")
            ),
            finished_at=_instant(request.get("finished_at")),
        )

    def includes(self, paper: PaperFacts) -> bool:
        if paper.run_ids.intersection(self.run_ids):
            return True
        if paper.paper_id in self.hashes or paper.content_sha256 in self.hashes:
            return True
        if paper.paths & self.paths:
            return True
        if not self.folders or not self._seen_in_time(paper.discovered_at):
            return False
        return any(
            path.startswith(folder + "/")
            for path in paper.paths
            for folder in self.folders
        )

    def sql(self, alias: str = "p") -> str:
        """The same test as :meth:`includes`, over ``papers`` rows named ``alias``."""
        path = path_sql(alias)
        tests = [
            "EXISTS (SELECT 1 FROM extractions e JOIN chunks c "
            f"ON c.chunk_id = e.chunk_id WHERE c.paper_id = {alias}.paper_id "
            f"AND e.run_id IN {in_list(list(self.run_ids))})"
        ]
        if self.hashes:
            hashes = in_list(sorted(self.hashes))
            tests.append(
                f"{alias}.paper_id IN {hashes} OR {alias}.content_sha256 IN {hashes}"
            )
        if self.paths:
            paths = in_list(sorted(self.paths))
            tests.append(
                f"{path} IN {paths} OR EXISTS (SELECT 1 FROM paper_paths pp "
                f"WHERE pp.paper_id = {alias}.paper_id AND pp.path IN {paths})"
            )
        for folder in self.folders:
            under = literal(folder + "/")
            in_time = (
                ""
                if self.finished_at is None
                else f" AND ({alias}.discovered_at IS NULL OR {alias}.discovered_at"
                f" <= {literal(_naive_utc(self.finished_at))}::TIMESTAMP)"
            )
            tests.append(
                f"(starts_with({path}, {under}) OR EXISTS (SELECT 1 FROM paper_paths "
                f"pp WHERE pp.paper_id = {alias}.paper_id AND starts_with(pp.path, "
                f"{under})))" + in_time
            )
        return "(" + " OR ".join(f"({test})" for test in tests) + ")"

    def _seen_in_time(self, discovered_at: datetime | None) -> bool:
        if self.finished_at is None or discovered_at is None:
            return True
        return discovered_at <= self.finished_at


_REQUEST_COLUMNS = (
    "request_id, status, locations, prompt_ids, model_id, chunker_id, "
    "requested_by, requested_at, started_at, finished_at, error"
)


def request_scope(rows: RowStore, request_id: str) -> RequestScope | None:
    found = rows.query(
        f"SELECT {_REQUEST_COLUMNS} FROM run_requests "  # nosec B608
        f"WHERE request_id = {literal(request_id)} LIMIT 1"
    )
    if not found:
        return None
    manifests = rows.query(
        "SELECT artifacts FROM source_manifests "  # nosec B608
        f"WHERE request_id = {literal(request_id)} LIMIT 1"
    )
    return RequestScope.of(
        found[0], _json_list(manifests[0]["artifacts"]) if manifests else None
    )


def requests_including(rows: RowStore, paper: PaperFacts) -> list[dict[str, Any]]:
    """The requests that covered ``paper``, newest first.

    Requests are few, so each is tested here. Manifests can be long, so only
    those that mention the paper's hash or one of its paths are read.
    """
    # A manifest keeps prefix and key apart, so a path is looked for by its file name.
    names = {path.rsplit("/", 1)[-1] for path in paper.paths}
    mentions = [
        literal(value)
        for value in (paper.content_sha256, paper.paper_id, *sorted(names))
        if value
    ]
    text = "CAST(artifacts AS VARCHAR)"
    manifests = {
        row["request_id"]: _json_list(row["artifacts"])
        for row in rows.query(
            "SELECT request_id, artifacts FROM source_manifests WHERE "  # nosec B608
            + " OR ".join(f"contains({text}, {m})" for m in dict.fromkeys(mentions))
        )
    }
    included = []
    for request in rows.query(
        f"SELECT {_REQUEST_COLUMNS} FROM run_requests "  # nosec B608
        "ORDER BY requested_at DESC, request_id"
    ):
        scope = RequestScope.of(request, manifests.get(request["request_id"]))
        if scope.includes(paper):
            included.append(
                {
                    "request_id": request["request_id"],
                    "status": request["status"],
                    "locations": _json_list(request["locations"]),
                    "prompt_ids": _json_list(request["prompt_ids"]),
                    "model_id": request["model_id"],
                    "chunker_id": request["chunker_id"],
                    "requested_by": request["requested_by"],
                    "requested_at": _iso(request["requested_at"]),
                    "finished_at": _iso(request["finished_at"]),
                }
            )
    return included


def path_sql(alias: str = "p") -> str:
    """A ``papers`` row's path, joined the way :class:`PaperFacts` joins it."""
    prefix = f"trim(coalesce({alias}.storage_prefix, ''), '/')"
    return (
        f"CASE WHEN {prefix} = '' THEN {alias}.storage_key "
        f"ELSE {prefix} || '/' || {alias}.storage_key END"
    )


def _json_list(value: Any) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return list(value) if isinstance(value, list | tuple) else []


def _join(prefix: str | None, key: str | None) -> str:
    prefix = (prefix or "").strip("/")
    return f"{prefix}/{key}" if prefix else str(key)


def _instant(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _naive_utc(value: datetime) -> str:
    """Timestamps are stored without a zone, in UTC."""
    return value.astimezone(UTC).replace(tzinfo=None).isoformat()


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value
