"""Semantic gate boundaries and real SQL behavior without paid model calls."""

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from phases_v2.app.adapters.primary.SearchAPI import PREFIX, register
from phases_v2.datasets.schemas import DATASETS
from phases_v2.review.contracts.review_validation import validate, validate_batch
from phases_v2.review.review_automation import CHECKS, ReviewFailed, automatic_review
from phases_v2.review.review_domain import assess
from phases_v2.review.review_model import LangchainReviewModel
from phases_v2.review.review_queries import fingerprint_sql
from phases_v2.review.review_report import render_report
from phases_v2.review.review_service import ReviewService
from phases_v2.search.adapters.secondary.DatasetExtractedItemsAdapter import (
    DatasetExtractedItemsAdapter,
)
from phases_v2.search.domain import SearchService
from phases_v2.search.fakes import FakeSemanticIndex


class SQLRows:
    """Test RowStore runs the production SQL; snapshots used only for version checks."""

    def __init__(self):
        self.db = duckdb.connect()
        self.version = 0
        self.specs = {s.name: s for s in DATASETS}
        for spec in DATASETS:
            columns = ",".join(
                f"{c.name} {('VARCHAR' if c.type == 'string' else c.type)}"
                for c in spec.columns
            )
            self.db.execute(
                f"CREATE TABLE {spec.name} ({columns}, PRIMARY KEY ({','.join(spec.primary_key)}))"
            )

    def write_rows(self, name, rows):
        columns = [c.name for c in self.specs[name].columns]
        for row in rows:
            self.db.execute(
                f"INSERT OR REPLACE INTO {name} VALUES ({','.join('?' for _ in columns)})",
                [row.get(c) for c in columns],
            )
        self.version += 1

    def query(self, sql):
        cursor = self.db.execute(sql)
        return [
            dict(zip([c[0] for c in cursor.description], r)) for r in cursor.fetchall()
        ]

    def snapshot(self):
        return self.version

    def at_snapshot(self, snapshot):
        return self


@pytest.fixture
def setup():
    rows = SQLRows()
    claim = dict(
        subject_process="social support",
        subject_change="decreases",
        subject_participant="people",
        direction="increases",
        target_process="stress",
        evidence_text="Reduced social support increases stress.",
    )
    rows.write_rows("papers", [dict(paper_id="p", file_name="paper.pdf")])
    rows.write_rows(
        "chunks", [dict(chunk_id="c", paper_id="p", text=claim["evidence_text"], seq=0)]
    )
    rows.write_rows(
        "prompts",
        [
            dict(
                prompt_id="pr",
                name="probabilistic_processes",
                template="Extract claims",
                output_key="relations",
            )
        ],
    )
    rows.write_rows(
        "extractions",
        [dict(extraction_id="e", status="succeeded", model_id="extractor")],
    )
    rows.write_rows(
        "extracted_items",
        [
            dict(
                item_id="i",
                extraction_id="e",
                paper_id="p",
                chunk_id="c",
                prompt_id="pr",
                text=json.dumps(claim),
            )
        ],
    )
    relation = dict(
        relation_id="r",
        relation_index=0,
        item_id="i",
        extraction_id="e",
        paper_id="p",
        chunk_id="c",
        prompt_id="pr",
        model_id="extractor",
        **claim,
    )
    rows.write_rows("probabilistic_relations", [relation])
    service = ReviewService(rows, validate_batch)
    app = FastAPI()
    register(
        app, SearchService(FakeSemanticIndex(), DatasetExtractedItemsAdapter(rows))
    )
    yield rows, service, TestClient(app)
    rows.db.close()


def decision(service, status="approved", **changes):
    r = service.queue()[0]
    return dict(
        reviewer="operator",
        decisions=[
            dict(
                relation_id=r["relation_id"],
                fingerprint=r["fingerprint"],
                previous_event_id=r["previous_event_id"],
                decision=status,
                note="Inspected qualification and source",
                **changes,
            )
        ],
    )


def test_pending_approval_revocation_counts_export_and_old_snapshot(setup):
    rows, service, client = setup
    assert client.get(PREFIX + "/effects").json()["total"] == 0
    service.decide(decision(service))
    page = client.get(PREFIX + "/effects").json()
    assert page["total"] == 1
    assert page["hits"][0]["review_status"] == "approved"
    exported = client.get(PREFIX + "/export", params={"mode": "effects"})
    [record] = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert record["subject_change"] == "decreases" and record["review_id"]
    service.decide(decision(service, "uncertain"))
    assert client.get(PREFIX + "/effects").json()["total"] == 0
    assert (
        client.get(
            PREFIX + "/effects", params={"snapshot": page["snapshot"]}
        ).status_code
        == 409
    )
    exported = client.get(PREFIX + "/export", params={"mode": "effects"})
    assert list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig")))) == []
    assert len(rows.query("SELECT * FROM effect_reviews")) == 2
    raw = client.get(PREFIX + "/keyword", params={"q": "stress"}).json()
    assert raw["total"] == 1 and raw["hits"][0]["review_status"] == "unreviewed"


@pytest.mark.parametrize(
    "table,column,value",
    [
        ("chunks", "text", "Changed source"),
        ("extracted_items", "text", '{"different":"payload"}'),
        ("probabilistic_relations", "subject_change", "increases"),
        ("prompts", "template", "New instructions"),
        ("extractions", "status", "failed"),
        ("extractions", "model_id", "changed-extractor"),
    ],
)
def test_mutation_invalidates_approval(setup, table, column, value):
    rows, service, client = setup
    service.decide(decision(service))
    rows.db.execute(f"UPDATE {table} SET {column} = ?", [value])
    assert client.get(PREFIX + "/effects").json()["total"] == 0


def test_stale_decision_cannot_overwrite_and_batch_preflights(setup):
    rows, service, _ = setup
    stale = decision(service)
    service.decide(decision(service, "rejected"))
    with pytest.raises(ValueError, match="Stale"):
        service.decide(stale)
    good = decision(service)
    good["decisions"].append({**good["decisions"][0], "relation_id": "missing"})
    with pytest.raises(ValueError, match="no longer exists"):
        service.decide(good)
    assert len(rows.query("SELECT * FROM effect_reviews")) == 1


def test_exact_quote_and_stale_projection_are_non_overridable(setup):
    rows, service, _ = setup
    rows.db.execute(
        "UPDATE probabilistic_relations SET evidence_text = 'Repaired quote'"
    )
    candidate = service.queue()[0]
    assert set(candidate["blockers"]) == {"evidence_not_exact", "stale_projection"}
    with pytest.raises(ValueError, match="Approval blocked"):
        service.decide(decision(service))
    service.decide(decision(service, "rejected"))


def test_concurrent_sibling_decisions_fail_closed_then_can_be_resolved(setup):
    rows, service, client = setup
    service.decide(decision(service))
    [event] = rows.query("SELECT * FROM effect_reviews")
    rows.write_rows(
        "effect_reviews",
        [
            {
                **event,
                "event_id": "sibling",
                "reviewed_at": event["reviewed_at"] + timedelta(seconds=1),
            }
        ],
    )
    assert client.get(PREFIX + "/effects").json()["total"] == 0
    service.clock = lambda: datetime.now(UTC) + timedelta(seconds=2)
    service.decide(decision(service))
    assert client.get(PREFIX + "/effects").json()["total"] == 1


def test_unicode_fingerprint_agrees_with_sql_and_html_escapes(setup):
    rows, service, _ = setup
    text = "Stress café 😀 </script><script>alert(1)</script>"
    rows.db.execute("UPDATE chunks SET text = ?", [text])
    from phases_v2.review.review_queries import QUEUE_FROM

    [computed] = rows.query(f"SELECT {fingerprint_sql()} AS fingerprint {QUEUE_FROM}")
    candidate = service.queue()[0]
    assert computed["fingerprint"] == candidate["fingerprint"]
    page = render_report([candidate])
    assert "&lt;script&gt;alert(1)" in page and "<script>alert(1)" not in page


@pytest.mark.parametrize(
    "field",
    [
        "source_qualification",
        "target_effect",
        "asserted_finding",
        "endpoints",
        "conditions",
        "participant",
    ],
)
def test_any_failed_check_blocks_model_approval(setup, field):
    _, service, client = setup
    verdict = dict(
        decision="approved",
        reason="Reviewer explanation",
        **dict.fromkeys(CHECKS, "pass"),
    )
    verdict[field] = "fail"
    model = SimpleNamespace(review=lambda *args: (verdict, json.dumps(verdict)))
    report = automatic_review(service, model, "test-model")
    assert report["rejected"] == 1 and report["calls"] == 1
    assert client.get(PREFIX + "/effects").json()["total"] == 0


def test_model_approval_records_provenance_and_is_not_called_twice(setup):
    rows, service, client = setup
    verdict = dict(
        decision="approved",
        reason="All conditions supported",
        **dict.fromkeys(CHECKS, "pass"),
    )
    model = SimpleNamespace(review=lambda *args: (verdict, json.dumps(verdict)))
    assert automatic_review(service, model, "test-model")["approved"] == 1
    assert automatic_review(service, model, "test-model")["calls"] == 0
    [event] = rows.query("SELECT * FROM effect_reviews")
    assert event["reviewer_kind"] == "model" and event["reviewer_model"] == "test-model"
    assert event["reviewer_prompt"] and event["reviewer_response"]
    assert client.get(PREFIX + "/effects").json()["total"] == 1


def test_pending_budget_skips_approved_and_respects_paper_scope(setup):
    rows, service, _ = setup
    service.decide(decision(service))
    [relation] = rows.query("SELECT * FROM probabilistic_relations")
    rows.write_rows("probabilistic_relations", [{**relation, "relation_id": "r2"}])
    assert service.queue(pending_only=True, limit=1)[0]["relation_id"] == "r2"
    assert service.queue(pending_only=True, paper_ids=[]) == []
    assert service.queue(pending_only=True, paper_ids=["not-selected"]) == []
    assert len(service.queue(pending_only=True, paper_ids=["p"])) == 1


def test_uncertain_check_cannot_be_promoted_to_approval(setup):
    _, service, client = setup
    verdict = dict(
        decision="approved", reason="Ambiguous source", **dict.fromkeys(CHECKS, "pass")
    )
    verdict["conditions"] = "uncertain"
    model = SimpleNamespace(review=lambda *args: (verdict, json.dumps(verdict)))
    assert automatic_review(service, model, "test-model")["uncertain"] == 1
    assert client.get(PREFIX + "/effects").json()["total"] == 0


@pytest.mark.parametrize(
    "source,change,target,effect,quote",
    [
        (
            "social relationship quality",
            "none",
            "affective wellbeing",
            "increases",
            "Higher relationship quality was associated with higher average affective wellbeing.",
        ),
        (
            "solitude",
            "none",
            "low arousal positive affect",
            "increases",
            "Momentary solitude was associated with increased low arousal positive affect.",
        ),
        (
            "aging",
            "increases",
            "time spent alone",
            "increases",
            "Greater age was linked with spending more time alone.",
        ),
        (
            "social interaction",
            "none",
            "wellbeing and happiness",
            "increases",
            "Social interaction contributes to wellbeing and happiness.",
        ),
        (
            "relationship quality",
            "increases",
            "negative affect",
            "prevents-increase",
            "Higher relationship quality was associated with lesser increases in negative affect.",
        ),
        (
            "solitude",
            "none",
            "anxiety",
            "no-effect",
            "Anxiety was unrelated to solitude; there was no statistically significant association.",
        ),
        (
            "solitude",
            "increases",
            "cortisol",
            "increases",
            "Greater solitude was associated with increased cortisol levels.",
        ),
    ],
)
def test_known_pilot_errors_stay_held_even_if_reviewer_passes_every_check(
    setup, source, change, target, effect, quote
):
    rows, service, client = setup
    [relation] = rows.query("SELECT * FROM probabilistic_relations")
    relation.update(
        subject_process=source,
        subject_change=change,
        target_process=target,
        direction=effect,
        evidence_text=quote,
    )
    rows.write_rows("probabilistic_relations", [relation])
    from phases_v2.review.review_domain import CLAIM_FIELDS

    rows.db.execute(
        "UPDATE extracted_items SET text = ?",
        [json.dumps({k: relation[k] for k in CLAIM_FIELDS})],
    )
    rows.db.execute("UPDATE chunks SET text = ?", [quote])
    verdict = dict(
        decision="approved", reason="All checks passed", **dict.fromkeys(CHECKS, "pass")
    )
    model = SimpleNamespace(review=lambda *args: (verdict, json.dumps(verdict)))
    assert automatic_review(service, model, "test-model")["uncertain"] == 1
    assert client.get(PREFIX + "/effects").json()["total"] == 0


def test_provider_failure_uncertain_and_no_calls_for_bad_evidence(setup):
    rows, service, client = setup

    def fail(*args):
        raise ReviewFailed("timeout", "partial response")

    report = automatic_review(service, SimpleNamespace(review=fail), "broken-model")
    assert report["uncertain"] == 1 and report["errors"]
    assert client.get(PREFIX + "/effects").json()["total"] == 0
    rows.db.execute("UPDATE chunks SET text = 'different text'")
    assert (
        automatic_review(service, SimpleNamespace(review=fail), "broken-model")["calls"]
        == 0
    )


@pytest.mark.parametrize(
    "payload",
    [
        dict(reviewer="", decisions=[]),
        dict(
            reviewer="x",
            decisions=[
                dict(
                    relation_id="r",
                    fingerprint="bad",
                    decision="approved",
                    note="reason",
                )
            ],
        ),
    ],
)
def test_decision_contract_runs_protovalidate(payload):
    with pytest.raises(ValueError):
        validate_batch(payload)


def test_model_adapter_rejects_missing_or_invalid_tool_fields():
    verdict = dict(decision="approved", reason="valid", **dict.fromkeys(CHECKS, "pass"))

    class Chat:
        def bind_tools(self, *args, **kwargs):
            return self

        def invoke(self, messages):
            assert messages[0]["role"] == "system"
            return SimpleNamespace(
                invalid_tool_calls=[],
                tool_calls=[dict(name="submit_review", args=verdict)],
                model_dump_json=lambda: json.dumps(verdict),
            )

    adapter = LangchainReviewModel(Chat())
    assert adapter.review("instructions", "source")[0]["decision"] == "approved"
    del verdict["conditions"]
    with pytest.raises(ReviewFailed):
        adapter.review("instructions", "source")
    with pytest.raises(ValueError):
        validate({**verdict, "conditions": "unknown"})


@pytest.mark.parametrize(
    "quote,direction,flag",
    [
        (
            "Higher quality relationships reported lesser increases in negative affect.",
            "prevents-increase",
            "attenuation_or_moderation",
        ),
        (
            "There was no statistically significant relationship.",
            "no-effect",
            "verify_null_effect_not_nonsignificance",
        ),
        (
            "We explored whether solitude improved wellbeing.",
            "increases",
            "verify_finding_not_study_intent",
        ),
    ],
)
def test_pilot_failure_patterns_are_flagged(setup, quote, direction, flag):
    _, service, _ = setup
    row = service.queue()[0]
    row.update(evidence_text=quote, chunk_text=quote, direction=direction)
    assert flag in assess(row)["flags"]
