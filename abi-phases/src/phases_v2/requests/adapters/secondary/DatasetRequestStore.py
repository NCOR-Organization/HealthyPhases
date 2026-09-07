"""The ``run_requests`` dataset, as the domain's :class:`RequestStore`."""

from __future__ import annotations

from phases_v2.ports import RowStore
from phases_v2.requests.interfaces import (
    PENDING,
    RequestNotFound,
    RunRequest,
)
from phases_v2.sql import literal

_COLUMNS = (
    "request_id, status, locations, chunker_id, prompt_id, model_id, "
    "requested_by, requested_at, started_at, finished_at, run_id, error"
)


class DatasetRequestStore:
    def __init__(self, rows: RowStore):
        self._rows = rows

    def save(self, request: RunRequest) -> None:
        self._rows.write_rows(
            "run_requests",
            [
                {
                    "request_id": request.request_id,
                    "status": request.status,
                    "locations": list(request.locations),
                    "chunker_id": request.chunker_id,
                    "prompt_id": request.prompt_id,
                    "model_id": request.model_id,
                    "requested_by": request.requested_by,
                    "requested_at": request.requested_at,
                    "started_at": request.started_at,
                    "finished_at": request.finished_at,
                    "run_id": request.run_id,
                    "error": request.error,
                }
            ],
        )

    def get(self, request_id: str) -> RunRequest:
        rows = self._rows.query(
            f"SELECT {_COLUMNS} FROM run_requests "  # nosec B608
            f"WHERE request_id = {literal(request_id)}"
        )
        if not rows:
            raise RequestNotFound(request_id)
        return _to_request(rows[0])

    def pending(self) -> list[RunRequest]:
        rows = self._rows.query(
            f"SELECT {_COLUMNS} FROM run_requests "  # nosec B608
            f"WHERE status = {literal(PENDING)} ORDER BY requested_at"
        )
        return [_to_request(row) for row in rows]

    def recent(self, limit: int = 50) -> list[RunRequest]:
        rows = self._rows.query(
            f"SELECT {_COLUMNS} FROM run_requests "  # nosec B608
            f"ORDER BY requested_at DESC LIMIT {int(limit)}"
        )
        return [_to_request(row) for row in rows]


def _to_request(row: dict) -> RunRequest:
    locations = row.get("locations") or []
    return RunRequest(
        request_id=row["request_id"],
        status=row["status"],
        locations=list(locations),
        chunker_id=row["chunker_id"],
        prompt_id=row["prompt_id"],
        model_id=row["model_id"],
        requested_by=row.get("requested_by"),
        requested_at=row.get("requested_at"),
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        run_id=row.get("run_id"),
        error=row.get("error"),
    )
