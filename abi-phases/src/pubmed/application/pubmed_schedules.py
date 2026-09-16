"""Recurring PubMed searches, independent of Phase v2 execution."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from pubmed.application.pubmed_service import PubmedService
from pubmed.contracts.pubmed_validation import validate
from pubmed.domain.pubmed_errors import RequestAlreadyClaimed


class PubmedSchedules:
    def __init__(
        self, publisher: PubmedService, clock: Callable[[], datetime] | None = None
    ) -> None:
        self.publisher = publisher
        self.store = publisher.store
        self.clock = clock or (lambda: datetime.now(UTC))

    def list(self) -> list[dict[str, Any]]:
        return sorted(
            self.store.rows("schedules"), key=lambda r: r["created_at"], reverse=True
        )

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = validate(
            "ScheduleCreate", {"enabled": True, "ingest_new": True, **payload}
        )
        query = self.publisher.one("queries", query_id=command["query_id"])
        now = self.clock()
        row = validate(
            "ScheduleRecord",
            {
                "schedule_id": str(uuid4()),
                "name": command["name"].strip(),
                "search": {
                    key: query[key]
                    for key in (
                        "query",
                        "start_date",
                        "end_date",
                        "sort",
                        "max_results",
                    )
                },
                "interval_hours": command["interval_hours"],
                "enabled": command["enabled"],
                "ingest_new": command["ingest_new"],
                "created_at": now.isoformat(),
                "next_run_at": (
                    now + timedelta(hours=command["interval_hours"])
                ).isoformat(),
                "status": "idle",
            },
        )
        self.store.save("schedules", [row])
        return row

    def toggle(self, schedule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        enabled = validate("ScheduleToggle", payload)["enabled"]

        def change(row):
            if enabled and not row["enabled"]:
                row["next_run_at"] = (
                    self.clock() + timedelta(hours=row["interval_hours"])
                ).isoformat()
            row["enabled"] = enabled
            return row

        return self.store.update_schedule(schedule_id, change)

    def due(self) -> list[dict[str, Any]]:
        now = self.clock()
        return sorted(
            [
                row
                for row in self.list()
                if row["enabled"]
                and row["status"] != "running"
                and datetime.fromisoformat(row["next_run_at"]) <= now
            ],
            key=lambda row: row["next_run_at"],
        )

    def execute(
        self, schedule_id: str, scheduled_at: str, run_id: str
    ) -> dict[str, Any] | None:
        now = self.clock()

        def claim(row):
            if (
                not row["enabled"]
                or row["status"] == "running"
                or row["next_run_at"] != scheduled_at
                or datetime.fromisoformat(scheduled_at) > now
            ):
                raise RequestAlreadyClaimed(schedule_id)
            row.update(
                status="running",
                run_id=run_id,
                last_started_at=now.isoformat(),
                last_finished_at="",
                error="",
                last_request_id="",
                last_query_id="",
                last_truncated=False,
                next_run_at=(now + timedelta(hours=row["interval_hours"])).isoformat(),
            )
            return row

        try:
            row = self.store.update_schedule(schedule_id, claim)
        except RequestAlreadyClaimed:
            return None
        try:
            result = self.publisher.search(row["search"])
            query_id = result["query"]["query_id"]
            request_id = ""
            if row["ingest_new"]:
                known = {
                    a["pmid"] for a in self.store.rows("artifacts", status="ready")
                }
                for request in self.store.rows("run_requests"):
                    if request["status"] in ("pending", "running"):
                        known.update(request["pmids"])
                pmids = [
                    p["pmid"]
                    for p in result["papers"]
                    if p["pmcid"] and p["pmid"] not in known
                ]
                if pmids:
                    request_id = self.publisher.submit(
                        {"query_id": query_id, "pmids": pmids}
                    )["request_id"]

            def finish(current):
                if current["run_id"] == run_id:
                    current.update(
                        status="succeeded",
                        last_finished_at=self.clock().isoformat(),
                        last_query_id=query_id,
                        last_request_id=request_id,
                        last_truncated=result["truncated"],
                    )
                return current

            return self.store.update_schedule(schedule_id, finish)
        except Exception:
            self.fail(
                schedule_id, run_id, "Scheduled search failed; inspect the Dagster run"
            )
            raise

    def fail(
        self, schedule_id: str, run_id: str, error: str, scheduled_at: str = ""
    ) -> dict[str, Any]:
        def change(row):
            unclaimed = (
                scheduled_at
                and row["next_run_at"] == scheduled_at
                and row["status"] != "running"
            )
            if unclaimed or (row["status"] == "running" and row["run_id"] == run_id):
                row.update(
                    status="failed",
                    error=error,
                    last_finished_at=self.clock().isoformat(),
                )
                if unclaimed:
                    row.update(
                        run_id=run_id,
                        next_run_at=(
                            self.clock() + timedelta(hours=row["interval_hours"])
                        ).isoformat(),
                    )
            return row

        return self.store.update_schedule(schedule_id, change)
