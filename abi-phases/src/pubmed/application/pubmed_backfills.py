"""Checkpointed full-query discovery feeding the existing publication queue."""

from __future__ import annotations

from uuid import UUID, uuid4, uuid5

from pubmed.application.pubmed_service import PubmedService, now
from pubmed.contracts.pubmed_validation import validate
from pubmed.domain.pubmed_errors import AcquisitionError, RequestAlreadyClaimed

BATCH_SIZE = 200
MAX_UID = 2_147_483_647
PARTITIONS_PER_RUN = 20
TERMINAL_REQUESTS = {"succeeded", "partial", "failed"}


class PubmedBackfills:
    def __init__(self, publisher: PubmedService):
        self.publisher = publisher
        self.store = publisher.store

    def create(self, payload: dict) -> dict:
        command = validate("BackfillCreate", payload)
        query = self.publisher.one("queries", query_id=command["query_id"])
        row = validate(
            "BackfillRecord",
            {
                "backfill_id": str(uuid4()),
                "source_query_id": query["query_id"],
                "query_id": str(uuid4()),
                "search": {
                    k: query[k]
                    for k in ("query", "start_date", "end_date", "sort", "max_results")
                },
                "status": "pending",
                "created_at": now(),
                "updated_at": now(),
                "ranges": [{"lower": 1, "upper": MAX_UID}],
                "total": query["total"],
            },
        )
        self.store.save("backfills", [row])
        return self.progress(row)

    def progress(self, row: dict) -> dict:
        result = {
            k: v
            for k, v in row.items()
            if k not in {"ranges", "active_pmids", "run_id"}
        }
        if row["current_request_id"]:
            request = self.publisher.one(
                "run_requests", request_id=row["current_request_id"]
            )
            counts = self._counts(request, final=False)
            for key, count in counts.items():
                result[key] += count
        result["remaining"] = max(0, result["discovered"] - result["completed"])
        result["discovery_complete"] = not row["ranges"]
        return validate("BackfillProgress", result)

    def list(self) -> list[dict]:
        return [
            self.progress(r)
            for r in sorted(
                self.store.rows("backfills"),
                key=lambda r: r["created_at"],
                reverse=True,
            )
        ]

    def due(self) -> list[dict]:
        rows = []
        for row in self.store.rows("backfills"):
            if row["status"] == "pending":
                rows.append(row)
            elif row["status"] == "waiting":
                request = self.publisher.one(
                    "run_requests", request_id=row["current_request_id"]
                )
                if request["status"] in TERMINAL_REQUESTS:
                    rows.append(row)
        return sorted(rows, key=lambda r: r["updated_at"])

    def resume(self, backfill_id: str) -> dict:
        def change(row):
            if row["status"] != "failed":
                raise ValueError("Only interrupted full ingestions need resuming")
            row.update(
                status="pending",
                error="",
                run_id="",
                updated_at=now(),
                generation=row["generation"] + 1,
            )
            return row

        return self.progress(self.store.update_backfill(backfill_id, change))

    def fail(self, backfill_id: str, generation: int, run_id: str, error: str) -> None:
        def change(row):
            if row["generation"] == generation and (
                (row["status"] == "running" and row["run_id"] == run_id)
                or row["status"] in {"pending", "waiting"}
            ):
                row.update(status="failed", error=error, updated_at=now())
            return row

        self.store.update_backfill(backfill_id, change)

    def _checkpoint(self, row: dict, status: str = "running") -> dict:
        def change(current):
            if (
                current["status"] != "running"
                or current["run_id"] != row["run_id"]
                or current["generation"] != row["generation"]
            ):
                raise RequestAlreadyClaimed(row["backfill_id"])
            return dict(
                row,
                status=status,
                updated_at=now(),
                generation=row["generation"] + (status != "running"),
            )

        return self.store.update_backfill(row["backfill_id"], change)

    @staticmethod
    def _counts(request: dict, final: bool) -> dict:
        outcomes = request["outcomes"]
        ready = sum(o["status"] == "ready" for o in outcomes.values())
        unavailable = sum(o["status"] == "unavailable" for o in outcomes.values())
        completed = len(request["pmids"]) if final else len(outcomes)
        return {
            "completed": completed,
            "published": ready,
            "unavailable": unavailable,
            "failed": completed - ready - unavailable,
        }

    def execute(self, backfill_id: str, generation: int, run_id: str) -> dict | None:
        def claim(row):
            if row["generation"] != generation or row["status"] not in {
                "pending",
                "waiting",
            }:
                raise RequestAlreadyClaimed(backfill_id)
            row.update(status="running", run_id=run_id, error="", updated_at=now())
            return row

        try:
            row = self.store.update_backfill(backfill_id, claim)
        except RequestAlreadyClaimed:
            return None
        try:
            if not row["initialized"]:
                total, _ = self.publisher.source.search_ids(row["search"])
                bounded, _ = self.publisher.source.search_ids(row["search"], 1, MAX_UID)
                if bounded != total:
                    raise AcquisitionError(
                        "PubMed changed during initialization or has IDs outside the supported range; resume to retry"
                    )
                row.update(total=total, initialized=True)
                self.store.save(
                    "queries",
                    [
                        {
                            **row["search"],
                            "query_id": row["query_id"],
                            "created_at": row["created_at"],
                            "total": total,
                            "contract_version": 1,
                        }
                    ],
                )
                row = self._checkpoint(row)

            if row["current_request_id"]:
                request = self.publisher.one(
                    "run_requests", request_id=row["current_request_id"]
                )
                if request["status"] not in TERMINAL_REQUESTS:
                    return self._checkpoint(row, "waiting")
                for key, count in self._counts(request, final=True).items():
                    row[key] += count
                row["current_request_id"] = ""
                row["ranges"].pop(0)
                row = self._checkpoint(row)

            for _ in range(PARTITIONS_PER_RUN):
                if not row["ranges"]:
                    row["finished_at"] = now()
                    return self._checkpoint(
                        row, "partial" if row["failed"] else "succeeded"
                    )
                interval = row["ranges"][0]
                if not row["active_pmids"]:
                    count, ids = self.publisher.source.search_ids(
                        row["search"], interval["lower"], interval["upper"], BATCH_SIZE
                    )
                    if count > BATCH_SIZE:
                        if interval["lower"] >= interval["upper"]:
                            raise AcquisitionError(
                                "PubMed returned an unsplittable result set"
                            )
                        midpoint = (interval["lower"] + interval["upper"]) // 2
                        row["ranges"][:1] = [
                            {"lower": interval["lower"], "upper": midpoint},
                            {"lower": midpoint + 1, "upper": interval["upper"]},
                        ]
                        row = self._checkpoint(row)
                        continue
                    if count != len(ids) or len(ids) != len(set(ids)):
                        raise AcquisitionError(
                            "Incomplete PubMed partition; resume to retry"
                        )
                    if not ids:
                        row["ranges"].pop(0)
                        row = self._checkpoint(row)
                        continue
                    row["active_pmids"] = ids
                    row = self._checkpoint(row)

                # Persisted identifiers remain fixed even when resuming after an outage.
                papers = self.publisher.source.summaries(row["active_pmids"])
                if {p["pmid"] for p in papers} != set(row["active_pmids"]):
                    raise AcquisitionError(
                        "Incomplete PubMed summaries; resume to retry"
                    )
                self.store.save("papers", papers)
                self.store.save(
                    "query_papers",
                    [
                        {"query_id": row["query_id"], "pmid": p}
                        for p in row["active_pmids"]
                    ],
                )
                request_id = str(
                    uuid5(UUID(backfill_id), f"{interval['lower']}:{interval['upper']}")
                )
                self.publisher.submit(
                    {"query_id": row["query_id"], "pmids": row["active_pmids"]},
                    request_id=request_id,
                )
                row["discovered"] += len(row["active_pmids"])
                row.update(current_request_id=request_id, active_pmids=[])
                return self._checkpoint(row, "waiting")
            return self._checkpoint(row, "pending")
        except RequestAlreadyClaimed:
            return None  # A cancellation or a newer owner fenced this worker out.
        except Exception:
            self.fail(
                backfill_id,
                generation,
                run_id,
                "Full ingestion interrupted; resume to retry and inspect the Dagster run",
            )
            raise
