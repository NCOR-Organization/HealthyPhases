"""Review use cases over the existing RowStore port; decisions are audit events."""

from datetime import UTC, datetime
from uuid import uuid4

from phases_v2.ports import RowStore
from phases_v2.review.review_domain import POLICY, assess
from phases_v2.review.review_queries import QUEUE_COLUMNS, QUEUE_FROM, fingerprint_sql
from phases_v2.sql import in_list, literal


class ReviewService:
    def __init__(
        self,
        rows: RowStore,
        validate,
        clock=lambda: datetime.now(UTC),
        new_id=lambda: str(uuid4()),
    ):
        self.rows, self.validate = rows, validate
        self.clock, self.new_id = clock, new_id

    def queue(
        self,
        *,
        after: str = "",
        limit: int = 100,
        paper_ids: list[str] | None = None,
        pending_only: bool = False,
    ) -> list[dict]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        scope = "" if paper_ids is None else f" AND r.paper_id IN {in_list(paper_ids)}"
        pending = (
            f" AND review.fingerprint IS DISTINCT FROM {fingerprint_sql()}"
            if pending_only
            else ""
        )
        return [
            self._present(r)
            for r in self.rows.query(
                f"SELECT {QUEUE_COLUMNS} {QUEUE_FROM} "
                f"WHERE r.relation_id > {literal(after)} {scope} {pending} ORDER BY r.relation_id LIMIT {limit}"
            )
        ]

    @staticmethod
    def _present(row):
        result = {**row, **assess(row)}
        result["previous_event_id"] = row.get("previous_event_id") or ""
        result["status"] = (
            row.get("previous_decision") or "pending"
            if row.get("reviewed_fingerprint") == result["fingerprint"]
            else "pending"
        )
        if row.get("review_conflict"):
            result["status"] = "uncertain"
            result["flags"].append("conflicting_reviews_require_resolution")
        if result["status"] == "approved" and result["blockers"]:
            result["status"] = "blocked"
        return result

    def decide(
        self,
        batch: dict,
        *,
        model_id: str = "",
        model_prompt: str = "",
        model_response: str = "",
        reviewer_kind: str = "",
    ) -> list[str]:
        self.validate(batch)
        if not batch["reviewer"].strip():
            raise ValueError("reviewer must not be blank")
        decisions = batch["decisions"]
        ids = [d["relation_id"] for d in decisions]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate relation decisions")
        found = {
            r["relation_id"]: self._present(r)
            for r in self.rows.query(
                f"SELECT {QUEUE_COLUMNS} {QUEUE_FROM} WHERE r.relation_id IN {in_list(ids)}"
            )
        }
        events = []
        for decision in decisions:
            row = found.get(decision["relation_id"])
            if row is None:
                raise ValueError("Relation no longer exists; export a fresh review")
            if (
                decision["fingerprint"] != row["fingerprint"]
                or decision.get("previous_event_id", "") != row["previous_event_id"]
            ):
                raise ValueError("Stale review; export a fresh review before deciding")
            if not decision["note"].strip():
                raise ValueError("Every decision requires a review note")
            if decision["decision"] == "approved" and row["blockers"]:
                raise ValueError("Approval blocked: " + ", ".join(row["blockers"]))
            events.append(
                {
                    **decision,
                    "previous_event_id": row["previous_event_id"],
                    "event_id": self.new_id(),
                    "policy": POLICY,
                    "reviewer": batch["reviewer"],
                    "reviewed_at": self.clock(),
                    "reviewer_kind": reviewer_kind
                    or ("model" if model_id else "human"),
                    "reviewer_model": model_id,
                    "reviewer_prompt": model_prompt,
                    "reviewer_response": model_response,
                }
            )
        # Preflight the complete batch before one write. A concurrent stale writer
        # produces sibling events; the search gate denies both until re-reviewed.
        self.rows.write_rows("effect_reviews", events)
        return [e["event_id"] for e in events]
