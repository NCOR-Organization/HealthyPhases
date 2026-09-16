from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pubmed.adapters.primary.pubmed_api import router
from pubmed.application.pubmed_schedules import PubmedSchedules


@pytest.fixture
def scheduler(service):
    return PubmedSchedules(service, clock=lambda: datetime(2026, 9, 16, 12, tzinfo=UTC))


def create(scheduler, **options):
    query = scheduler.publisher.search(
        {"query": "solitude", "start_date": "2026-01-01"}
    )["query"]
    return scheduler.create(
        {
            "query_id": query["query_id"],
            "name": "New solitude papers",
            "interval_hours": 24,
            **options,
        }
    )


def advance(scheduler, row):
    scheduler.clock = lambda: datetime.fromisoformat(row["next_run_at"])


def test_creation_is_explicit_and_copies_the_saved_query(scheduler):
    assert scheduler.list() == []
    row = create(scheduler)
    assert row["search"]["start_date"] == "2026-01-01"
    assert row["search"]["query"] == "solitude"
    assert row["next_run_at"] == "2026-09-17T12:00:00+00:00"
    assert row["enabled"] is True
    assert not scheduler.publisher.requests()
    assert scheduler.due() == []


@pytest.mark.parametrize(
    "change",
    [{"name": " "}, {"interval_hours": 0}, {"interval_hours": 2}, {"enabled": "yes"}],
)
def test_invalid_schedule_commands_use_contract_validation(scheduler, change):
    with pytest.raises(ValueError):
        create(scheduler, **change)
    assert not scheduler.list()


def test_disabled_schedules_and_stale_queued_runs_do_not_search(scheduler):
    row = create(scheduler)
    advance(scheduler, row)
    assert len(scheduler.due()) == 1
    scheduler.toggle(row["schedule_id"], {"enabled": False})
    assert scheduler.due() == []
    assert scheduler.execute(row["schedule_id"], row["next_run_at"], "stale") is None
    enabled = scheduler.toggle(row["schedule_id"], {"enabled": True})
    assert enabled["next_run_at"] != row["next_run_at"]
    assert scheduler.execute(row["schedule_id"], row["next_run_at"], "stale") is None
    assert len(scheduler.publisher.queries()) == 1


def test_recurring_search_only_queues_new_downloadable_papers(scheduler):
    row = create(scheduler)
    advance(scheduler, row)
    first = scheduler.execute(row["schedule_id"], row["next_run_at"], "first")
    assert first["status"] == "succeeded"
    request = scheduler.publisher.requests()[0]
    assert request["pmids"] == ["1", "2"]
    assert not scheduler.publisher.storage.files
    assert (
        scheduler.execute(row["schedule_id"], row["next_run_at"], "duplicate") is None
    )
    advance(scheduler, first)
    second = scheduler.execute(row["schedule_id"], first["next_run_at"], "second")
    assert second["last_request_id"] == ""  # Both papers already queued.
    scheduler.publisher.execute(request["request_id"], "download")
    advance(scheduler, second)
    third = scheduler.execute(row["schedule_id"], second["next_run_at"], "third")
    assert third["last_request_id"] == ""  # Both papers already published.
    assert len(scheduler.publisher.requests()) == 1


def test_search_only_schedule_never_queues_downloads(scheduler):
    row = create(scheduler, ingest_new=False)
    advance(scheduler, row)
    result = scheduler.execute(row["schedule_id"], row["next_run_at"], "search-only")
    assert result["last_query_id"]
    assert not scheduler.publisher.requests()


def test_disabling_an_active_search_is_preserved_on_completion(scheduler):
    row = create(scheduler)
    original = scheduler.publisher.source.search

    def search(parameters):
        scheduler.toggle(row["schedule_id"], {"enabled": False})
        return original(parameters)

    scheduler.publisher.source.search = search
    advance(scheduler, row)
    finished = scheduler.execute(row["schedule_id"], row["next_run_at"], "active")
    assert finished["enabled"] is False
    assert finished["status"] == "succeeded"


def test_failures_are_visible_and_missed_intervals_do_not_replay(scheduler):
    row = create(scheduler)
    scheduler.clock = lambda: datetime(2026, 9, 30, 12, tzinfo=UTC)

    def broken(_):
        raise OSError("upstream unavailable")

    scheduler.publisher.source.search = broken
    with pytest.raises(OSError):
        scheduler.execute(row["schedule_id"], row["next_run_at"], "failed-run")
    failed = scheduler.list()[0]
    assert failed["status"] == "failed" and failed["error"]
    assert datetime.fromisoformat(
        failed["next_run_at"]
    ) == scheduler.clock() + timedelta(days=1)
    assert scheduler.due() == []


def test_http_create_list_toggle_and_validation(service):
    app = FastAPI()
    app.include_router(router(service))
    client = TestClient(app)
    query = service.search({"query": "solitude"})["query"]
    response = client.post(
        "/pubmed/api/schedules",
        json={"query_id": query["query_id"], "name": "Daily", "interval_hours": 24},
    )
    assert response.status_code == 201
    row = response.json()
    assert client.get("/pubmed/api/schedules").json()["schedules"][0]["enabled"] is True
    url = "/pubmed/api/schedules/" + row["schedule_id"]
    assert client.patch(url, json={"enabled": False}).json()["enabled"] is False
    assert client.patch(url, json={}).status_code == 422
    assert (
        client.patch(
            "/pubmed/api/schedules/missing", json={"enabled": True}
        ).status_code
        == 404
    )


def test_failure_before_claim_advances_the_occurrence_and_keeps_pause(scheduler):
    row = create(scheduler)
    advance(scheduler, row)
    scheduler.toggle(row["schedule_id"], {"enabled": False})
    failed = scheduler.fail(
        row["schedule_id"],
        "failed-before-claim",
        "Worker could not start",
        row["next_run_at"],
    )
    assert failed["status"] == "failed"
    assert failed["enabled"] is False
    assert failed["next_run_at"] != row["next_run_at"]
    assert scheduler.execute(row["schedule_id"], row["next_run_at"], "stale") is None


def test_dagster_scheduled_job_refreshes_and_queues_once(monkeypatch, scheduler):
    import dagster as dg

    from pubmed.orchestrations.pubmed_orchestration import (
        build_schedule_run_requests,
        scheduled_query_job,
    )

    row = create(scheduler)
    advance(scheduler, row)
    requests = build_schedule_run_requests(scheduler.due())
    assert len(requests) == 1
    assert (
        requests[0].run_key == build_schedule_run_requests(scheduler.due())[0].run_key
    )
    monkeypatch.setattr(
        "pubmed.orchestrations.pubmed_orchestration.schedules", lambda: scheduler
    )
    with dg.DagsterInstance.ephemeral() as instance:
        result = scheduled_query_job.execute_in_process(
            run_config=requests[0].run_config, instance=instance
        )
    assert result.success
    assert scheduler.list()[0]["status"] == "succeeded"
    assert len(scheduler.publisher.requests()) == 1
    assert scheduler.due() == []
