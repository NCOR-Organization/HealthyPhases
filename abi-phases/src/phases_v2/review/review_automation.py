"""Bounded second-pass review through an injected model port."""

import json
from importlib.resources import files
from typing import Protocol

from phases_v2.review import __name__ as package_name
from phases_v2.review.review_domain import AUTOMATIC_HOLD_FLAGS, CLAIM_FIELDS

CHECKS = (
    "source_qualification",
    "target_effect",
    "asserted_finding",
    "endpoints",
    "conditions",
    "participant",
)


class ReviewModel(Protocol):
    def review(self, instructions: str, source: str) -> tuple[dict, str]:
        """Return a validated verdict and the raw provider response."""
        ...


class ReviewFailed(Exception):
    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


def checked_decision(verdict: dict, flags: list[str]) -> tuple[str, str]:
    checks = [verdict[k] for k in CHECKS]
    decision = verdict["decision"]
    if decision == "approved" and any(v != "pass" for v in checks):
        decision = "rejected" if "fail" in checks else "uncertain"
    note = verdict["reason"]
    holds = sorted(AUTOMATIC_HOLD_FLAGS.intersection(flags))
    if decision == "approved" and holds:
        decision = "uncertain"
        note = (
            "Automatic approval held: " + ", ".join(holds) + ". Model reason: " + note
        )[:4000]
    return decision, note


def automatic_review(
    service, model: ReviewModel, model_id: str, *, after="", limit=100, paper_ids=None
) -> dict:
    instructions = files(package_name).joinpath("review_prompt.txt").read_text()
    rows = service.queue(
        after=after, limit=limit, paper_ids=paper_ids, pending_only=True
    )
    report = {
        "examined": len(rows),
        "calls": 0,
        "approved": 0,
        "rejected": 0,
        "uncertain": 0,
        "skipped": 0,
        "errors": {},
        "next_after": rows[-1]["relation_id"] if rows else None,
    }
    for row in rows:
        if row["status"] != "pending":
            report["skipped"] += 1
            continue
        raw = ""
        source = json.dumps(
            {
                "claim": {k: row[k] for k in CLAIM_FIELDS},
                "chunk_text": row["chunk_text"],
                "flags": row["flags"],
            },
            ensure_ascii=False,
        )
        if row["blockers"]:
            decision, note = "rejected", "Hard checks: " + ", ".join(row["blockers"])
            reviewer = "automatic-evidence-check"
        else:
            reviewer = model_id
            report["calls"] += 1
            try:
                verdict, raw = model.review(instructions, source)
                decision, note = checked_decision(verdict, row["flags"])
            except ReviewFailed as error:
                decision, note, raw = (
                    "uncertain",
                    "Reviewer failed: " + str(error)[:3500],
                    error.raw,
                )
                report["errors"][row["relation_id"]] = note
        try:
            service.decide(
                {
                    "reviewer": reviewer,
                    "decisions": [
                        {
                            "relation_id": row["relation_id"],
                            "fingerprint": row["fingerprint"],
                            "previous_event_id": row["previous_event_id"],
                            "decision": decision,
                            "note": note,
                        }
                    ],
                },
                model_id="" if row["blockers"] else model_id,
                model_prompt=instructions + "\n\n" + source,
                model_response=raw,
                reviewer_kind="automatic" if row["blockers"] else "model",
            )
        except ValueError as error:
            report["errors"][row["relation_id"]] = str(error)
            continue
        report[decision] += 1
    return report
