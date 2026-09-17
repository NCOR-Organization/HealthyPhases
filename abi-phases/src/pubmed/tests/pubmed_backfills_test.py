from copy import deepcopy
from uuid import uuid4

import pytest

from pubmed.application.pubmed_backfills import PubmedBackfills
from pubmed.application.pubmed_service import PubmedService
from pubmed.domain.pubmed_errors import AcquisitionError
from pubmed.tests.pubmed_service_test import FakeSource, MemoryStorage, MemoryStore


class RangeSource(FakeSource):
    def __init__(self, count=450):
        super().__init__()
        self.ids = [str(i) for i in range(1, count + 1)]
        self.pages = []
        self.summary_calls = []

    def search_ids(self, parameters, lower=None, upper=None, limit=200):
        ids = [p for p in self.ids if lower is None or lower <= int(p) <= upper]
        self.pages.append((lower, upper))
        return len(ids), ids[:limit]

    def summaries(self, ids):
        self.summary_calls.append(list(ids))
        return [{"pmid": p, "pmcid": "PMC" + p, "title": "Paper " + p} for p in ids]


def setup(count=450, store=None):
    publisher = PubmedService(
        store or MemoryStore(), RangeSource(count), MemoryStorage()
    )
    query = publisher.search({"query": "solitude", "max_results": 1})["query"]
    backfills = PubmedBackfills(publisher)
    row = backfills.create({"query_id": query["query_id"]})
    return publisher, backfills, row


def advance(publisher, backfills, row):
    return backfills.execute(row["backfill_id"], row["generation"], str(uuid4()))


def finish(publisher, backfills, row):
    for _ in range(1000):
        row = advance(publisher, backfills, row)
        if row["status"] == "waiting":
            publisher.execute(row["current_request_id"], str(uuid4()))
        elif row["status"] in {"succeeded", "partial"}:
            return row
    pytest.fail("Backfill failed to terminate")


def test_all_results_exceed_preview_and_ncbi_single_search_ceiling():
    publisher, backfills, row = setup(10_050)
    # No network/storage download needed to verify complete partition enumeration.
    publisher._publish = lambda pmid: {"artifact_id": pmid}
    row = finish(publisher, backfills, row)
    assert row["discovered"] == row["completed"] == row["published"] == 10_050
    assert row["status"] == "succeeded"
    assert publisher.store.member_count(row["query_id"]) == 10_050
    requests = publisher.store.rows("run_requests")
    assert max(len(r["pmids"]) for r in requests) <= 200
    assert sorted(int(p) for r in requests for p in r["pmids"]) == list(
        range(1, 10_051)
    )
    assert len(publisher.papers(row["query_id"])) == 1000
    with pytest.raises(ValueError, match="full ingestion"):
        publisher.submit({"query_id": row["query_id"]})


def test_creation_queues_no_download_and_preserves_saved_dates():
    publisher, backfills, row = setup(5)
    assert not publisher.source.pages and not publisher.source.calls
    assert not publisher.store.rows("run_requests")
    query = publisher.search(
        {"query": "q", "start_date": "1900-01-01", "end_date": "2020-01-01"}
    )["query"]
    saved = backfills.create({"query_id": query["query_id"]})
    assert saved["search"]["start_date"] == "1900-01-01"
    assert saved["search"]["end_date"] == "2020-01-01"


def test_waits_for_publication_then_reports_per_paper_outcomes():
    publisher, backfills, row = setup(3)
    publisher.source.fail = {"PMC2"}
    row = advance(publisher, backfills, row)
    assert row["status"] == "waiting"
    assert backfills.due() == []
    publisher.execute(row["current_request_id"], "download")
    assert len(backfills.due()) == 1
    progress = backfills.list()[0]
    assert not {"ranges", "active_pmids", "run_id"} & progress.keys()
    assert (progress["published"], progress["unavailable"], progress["remaining"]) == (
        2,
        1,
        0,
    )
    row = advance(publisher, backfills, row)
    assert row["status"] == "succeeded"
    assert (row["published"], row["unavailable"], row["failed"]) == (2, 1, 0)


def test_progress_contract_rejects_negative_counts():
    from pubmed.contracts.pubmed_validation import validate

    _, _, progress = setup(3)
    with pytest.raises(ValueError):
        validate("BackfillProgress", dict(progress, discovered=-1))


def test_partial_publication_is_not_misreported_as_all_pdfs_published():
    publisher, backfills, row = setup(3)

    def publish(pmid):
        if pmid == "2":
            raise AcquisitionError("Temporary failure")
        return {"artifact_id": pmid}

    publisher._publish = publish
    row = finish(publisher, backfills, row)
    assert row["status"] == "partial"
    assert (row["published"], row["failed"], row["completed"]) == (2, 1, 3)


def test_resume_after_queue_commit_reuses_request_and_checkpoint(monkeypatch):
    publisher, backfills, row = setup(3)
    real_update = publisher.store.update_backfill
    broken = False

    def interrupted(key, change):
        nonlocal broken

        def apply(current):
            nonlocal broken
            updated = change(current)
            if updated["status"] == "waiting" and not broken:
                broken = True
                raise OSError("Crash after child request commit")
            return updated

        return real_update(key, apply)

    monkeypatch.setattr(publisher.store, "update_backfill", interrupted)
    with pytest.raises(OSError):
        advance(publisher, backfills, row)
    request = publisher.store.rows("run_requests")[0]
    publisher.execute(request["request_id"], "download")
    pages = len(publisher.source.pages)
    row = backfills.resume(row["backfill_id"])
    row = advance(publisher, backfills, row)
    assert len(publisher.source.pages) == pages
    assert len(publisher.store.rows("run_requests")) == 1
    assert (
        publisher.one("run_requests", request_id=request["request_id"])["status"]
        == "succeeded"
    )
    row = advance(publisher, backfills, row)
    assert row["status"] == "succeeded" and row["completed"] == 3


def test_duplicate_occurrences_and_late_failure_do_not_change_newer_state():
    publisher, backfills, row = setup(3)
    old = deepcopy(row)
    row = advance(publisher, backfills, row)
    assert advance(publisher, backfills, old) is None
    backfills.fail(row["backfill_id"], old["generation"], "old-run", "late failure")
    assert backfills.list()[0]["status"] == "waiting"
    with pytest.raises(ValueError, match="interrupted"):
        backfills.resume(row["backfill_id"])


def test_canceled_queued_occurrence_can_resume_with_a_new_run_key():
    publisher, backfills, row = setup(3)
    backfills.fail(row["backfill_id"], row["generation"], "canceled", "Canceled")
    resumed = backfills.resume(row["backfill_id"])
    assert resumed["generation"] > row["generation"]
    assert advance(publisher, backfills, row) is None
    assert finish(publisher, backfills, resumed)["status"] == "succeeded"


def test_empty_result_finishes_without_publication_request():
    publisher, backfills, row = setup(0)
    row = advance(publisher, backfills, row)
    assert row["status"] == "succeeded" and row["discovered"] == 0
    assert publisher.store.rows("run_requests") == []


def test_incomplete_partition_cannot_silently_finish(monkeypatch):
    publisher, backfills, row = setup(3)
    monkeypatch.setattr(publisher.source, "search_ids", lambda *a: (3, ["1"]))
    with pytest.raises(AcquisitionError, match="Incomplete"):
        advance(publisher, backfills, row)
    assert backfills.list()[0]["status"] == "failed"
    assert not publisher.store.rows("run_requests")


def test_missing_summary_preserves_the_identifiers_for_resume(monkeypatch):
    publisher, backfills, row = setup(3)
    monkeypatch.setattr(publisher.source, "summaries", lambda ids: [])
    with pytest.raises(AcquisitionError, match="summaries"):
        advance(publisher, backfills, row)
    saved = publisher.store.rows("backfills")[0]
    assert saved["active_pmids"] == ["1", "2", "3"]
    assert saved["discovered"] == 0


def test_api_is_authenticated_and_queues_full_search(service, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from pubmed.adapters.primary.pubmed_api import router

    monkeypatch.setenv("ABI_API_KEY", "test-key")
    query = service.search({"query": "solitude"})["query"]
    app = FastAPI()
    app.include_router(router(service))
    client = TestClient(app)
    assert (
        client.post(
            "/pubmed/api/backfills", json={"query_id": query["query_id"]}
        ).status_code
        == 401
    )
    client.headers["Authorization"] = "Bearer test-key"
    assert (
        client.post("/pubmed/api/backfills", json={"query_id": "bad"}).status_code
        == 422
    )
    response = client.post(
        "/pubmed/api/backfills", json={"query_id": query["query_id"]}
    )
    assert response.status_code == 201 and response.json()["status"] == "pending"
    assert len(client.get("/pubmed/api/backfills").json()["backfills"]) == 1
    assert not service.store.rows("run_requests")


def test_backfill_job_and_sensor_are_registered_with_stable_occurrence_keys():
    from pubmed.orchestrations.pubmed_orchestration import (
        PubmedOrchestration,
        build_backfill_run_requests,
    )

    definitions = PubmedOrchestration.New().definitions
    assert "pubmed_backfill" in {job.name for job in definitions.jobs}
    assert "pubmed_backfill_sensor" in {sensor.name for sensor in definitions.sensors}
    rows = [{"backfill_id": "b", "generation": 2}]
    request = build_backfill_run_requests(rows)[0]
    assert request.run_key == "b:2"
    assert request.run_config["ops"]["advance_backfill"]["config"]["generation"] == 2


def test_dagster_cancellation_reconciles_backfill_and_preserves_resume(monkeypatch):
    import dagster as dg
    from dagster._core.storage.dagster_run import DagsterRun

    from pubmed.orchestrations.pubmed_orchestration import cancellation_sensor

    publisher, backfills, row = setup(3)
    monkeypatch.setattr(
        "pubmed.orchestrations.pubmed_orchestration.backfills", lambda: backfills
    )
    run = DagsterRun(
        job_name="pubmed_backfill",
        run_id="cancelled",
        tags={
            "pubmed/backfill_id": row["backfill_id"],
            "pubmed/backfill_generation": "0",
        },
    )
    event = dg.DagsterEvent(
        event_type_value="PIPELINE_CANCELED", job_name="pubmed_backfill"
    )
    with dg.DagsterInstance.ephemeral() as instance:
        context = dg.build_run_status_sensor_context(
            "pubmed_cancellation_sensor", event, instance, run
        )
        cancellation_sensor(context)
    assert backfills.list()[0]["status"] == "failed"
    assert (
        finish(publisher, backfills, backfills.resume(row["backfill_id"]))["status"]
        == "succeeded"
    )


def test_a_new_full_ingestion_reuses_existing_published_pdfs():
    publisher, backfills, row = setup(3)
    finish(publisher, backfills, row)
    assert len(publisher.source.calls) == 3
    next_row = backfills.create({"query_id": row["source_query_id"]})
    finish(publisher, backfills, next_row)
    assert len(publisher.source.calls) == 3
    assert len(publisher.store.rows("artifacts")) == 3


def test_whole_range_mismatch_is_visible_instead_of_truncating(monkeypatch):
    publisher, backfills, row = setup(3)
    original = publisher.source.search_ids

    def mismatched(parameters, lower=None, upper=None, limit=200):
        count, ids = original(parameters, lower, upper, limit)
        return (count + 1, ids) if lower is None else (count, ids)

    monkeypatch.setattr(publisher.source, "search_ids", mismatched)
    with pytest.raises(AcquisitionError, match="initialization"):
        advance(publisher, backfills, row)
    assert not publisher.store.rows("run_requests")
    assert backfills.list()[0]["status"] == "failed"
