"""The HTTP surface the app talks to."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from phases_v2.app.adapters.primary.PipelineAPI import PREFIX, register
from phases_v2.app.service import PipelineAppService
from phases_v2.requests.fakes import FakeRequestStore


class _Rows:
    def query(self, sql):
        if "extraction_runs" in sql:
            return [{"succeeded": 3, "failed": 0, "skipped": 1}]
        return [{"chunker_id": "window_1_aaa"}]


class _Storage:
    def list_objects(self, prefix):
        return [f"{prefix}/solitude", f"{prefix}/gero"]


@pytest.fixture
def client():
    app = FastAPI()
    service = PipelineAppService(
        request_store=FakeRequestStore(), object_storage=_Storage(), rows=_Rows()
    )
    register(app, service)
    return TestClient(app)


def _valid_body():
    return {
        "locations": ["papers"],
        "chunker_id": "window_1_aaa",
        "prompt_ids": ["claims_abc"],
        "model_id": "openai/gpt-4.1-mini",
    }


def test_the_choices_a_user_makes_are_all_offered(client):
    assert client.get(f"{PREFIX}/prompts").json()["prompts"]
    assert client.get(f"{PREFIX}/models").json()["models"]
    assert client.get(f"{PREFIX}/chunkers").json()["chunkers"]
    locations = client.get(f"{PREFIX}/locations").json()["locations"]
    # Scoped to the module's own prefix, never the shared storage root.
    assert all(loc["prefix"].startswith("phases_v2") for loc in locations)
    assert locations[0]["prefix"] == "phases_v2"


def test_submitting_a_run_records_a_request(client):
    response = client.post(f"{PREFIX}/requests", json=_valid_body())

    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert response.json()["request_id"]


def test_a_missing_input_is_refused_with_the_field_named(client):
    body = _valid_body() | {"model_id": ""}

    response = client.post(f"{PREFIX}/requests", json=body)

    assert response.status_code == 422
    assert "model_id" in response.json()["detail"]


def test_submitting_with_no_location_is_refused(client):
    body = _valid_body() | {"locations": []}

    response = client.post(f"{PREFIX}/requests", json=body)

    assert response.status_code == 422
    assert "locations" in response.json()["detail"]


def test_a_submitted_request_can_be_followed(client):
    request_id = client.post(f"{PREFIX}/requests", json=_valid_body()).json()[
        "request_id"
    ]

    response = client.get(f"{PREFIX}/requests/{request_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_a_completed_request_reports_its_counts(client):
    request_id = client.post(f"{PREFIX}/requests", json=_valid_body()).json()[
        "request_id"
    ]

    counts = client.get(f"{PREFIX}/requests/{request_id}").json()["counts"]

    assert counts["succeeded"] == 3
    assert counts["failed"] == 0
    assert counts["skipped"] == 1


def test_requests_are_listed(client):
    client.post(f"{PREFIX}/requests", json=_valid_body())

    assert len(client.get(f"{PREFIX}/requests").json()["requests"]) == 1


def test_an_unknown_request_is_a_404_not_a_crash(client):
    assert client.get(f"{PREFIX}/requests/nope").status_code == 404


def test_choosing_a_different_chunker_returns_a_warning(client):
    response = client.get(f"{PREFIX}/chunker-warning", params={"chunker_id": "other"})

    assert response.json()["warning"]


def test_the_chunker_already_in_use_returns_no_warning(client):
    response = client.get(
        f"{PREFIX}/chunker-warning", params={"chunker_id": "window_1_aaa"}
    )

    assert response.json()["warning"] is None


def test_the_models_endpoint_reports_availability():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from phases_v2.models.catalog import DECLARED_MODELS

    usable = DECLARED_MODELS[0].model_id
    app = FastAPI()
    service = PipelineAppService(
        request_store=FakeRequestStore(),
        is_model_available=lambda model_id: model_id == usable,
    )
    register(app, service)

    models = TestClient(app).get(f"{PREFIX}/models").json()["models"]

    by_id = {m["model_id"]: m["available"] for m in models}
    assert by_id[usable] is True
    assert all(v is False for k, v in by_id.items() if k != usable)
