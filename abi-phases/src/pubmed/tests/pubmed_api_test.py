from fastapi import FastAPI
from fastapi.testclient import TestClient

from pubmed.adapters.primary.pubmed_api import router


def test_http_validation_submission_and_status(service, monkeypatch):
    monkeypatch.setenv("ABI_API_KEY", "pubmed-test-key")
    app = FastAPI()
    app.include_router(router(service))
    client = TestClient(app, headers={"Authorization": "Bearer pubmed-test-key"})
    assert client.post("/pubmed/api/search", json={"query": ""}).status_code == 422
    query = client.post("/pubmed/api/search", json={"query": "solitude"}).json()[
        "query"
    ]
    submitted = client.post(
        "/pubmed/api/requests", json={"query_id": query["query_id"]}
    )
    assert submitted.status_code == 201
    row = client.get("/pubmed/api/requests/" + submitted.json()["request_id"]).json()
    assert row["status"] == "pending"
    assert client.get("/pubmed/api/requests/missing").status_code == 404
    assert not service.source.calls


def test_orchestration_mapping_is_stable():
    from pubmed.orchestrations.pubmed_orchestration import (
        PubmedOrchestration,
        build_run_requests,
    )

    rows = [{"request_id": "one"}, {"request_id": "two"}]
    assert [r.run_key for r in build_run_requests(rows)] == ["one", "two"]
    assert (
        build_run_requests(rows)[0].run_config["ops"]["publish_papers"]["config"][
            "request_id"
        ]
        == "one"
    )
    assert PubmedOrchestration.New().definitions is not None


def test_local_module_is_discoverable_and_mounts_its_api(monkeypatch, service):
    from types import SimpleNamespace

    from naas_abi_core.module.ModuleOrchestrationLoader import ModuleOrchestrationLoader

    from pubmed import ABIModule

    monkeypatch.setattr("pubmed.pubmed_factory.service", lambda *_args: service)
    engine = SimpleNamespace(services=SimpleNamespace(dataset_available=lambda: True))
    module = ABIModule(engine, ABIModule.Configuration.model_construct())
    app = FastAPI()
    module.api(app)
    assert TestClient(app).get("/pubmed/api/queries").status_code == 200
    classes = ModuleOrchestrationLoader.load_orchestrations(ABIModule)
    assert len(classes) == 1
    assert classes[0].New().definitions.jobs[0].name == "pubmed_publish"


def test_canceled_job_marks_request_failed_and_allows_retry(monkeypatch, service):
    import dagster as dg
    from dagster._core.storage.dagster_run import DagsterRun

    from pubmed.orchestrations.pubmed_orchestration import cancellation_sensor
    from pubmed.tests.pubmed_service_test import queue

    row = queue(service)
    service.store.claim(row["request_id"], "canceled-run")
    monkeypatch.setattr(
        "pubmed.orchestrations.pubmed_orchestration.service", lambda: service
    )
    run = DagsterRun(
        job_name="pubmed_publish",
        run_id="canceled-run",
        tags={"pubmed/request_id": row["request_id"]},
    )
    event = dg.DagsterEvent(
        event_type_value="PIPELINE_CANCELED", job_name="pubmed_publish"
    )
    with dg.DagsterInstance.ephemeral() as instance:
        context = dg.build_run_status_sensor_context(
            "pubmed_cancellation_sensor", event, instance, run
        )
        cancellation_sensor(context)
    assert (
        service.one("run_requests", request_id=row["request_id"])["status"] == "failed"
    )
    assert service.retry(row["request_id"])["status"] == "pending"


def test_pubmed_mutations_require_authentication(service, monkeypatch):
    monkeypatch.setenv("ABI_API_KEY", "pubmed-test-key")
    app = FastAPI()
    app.include_router(router(service))
    client = TestClient(app)
    for method, path in [
        ("post", "/search"),
        ("post", "/requests"),
        ("post", "/schedules"),
        ("patch", "/schedules/id"),
        ("delete", "/schedules/id"),
        ("post", "/requests/id/retry"),
    ]:
        assert client.request(method, "/pubmed/api" + path, json={}).status_code in (
            401,
            403,
        )
