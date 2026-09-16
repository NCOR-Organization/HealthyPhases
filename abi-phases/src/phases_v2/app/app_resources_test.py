"""Resource lifecycle against the existing dataset adapter and HTTP boundary."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2.app.adapters.primary.PipelineAPI import PREFIX, register
from phases_v2.app.service import PipelineAppService
from phases_v2.chunking.chunkers import WINDOW_512_128
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.store import ensure_datasets
from phases_v2.models.catalog import DECLARED_MODELS
from phases_v2.prompts.templates import declared_prompts
from phases_v2.requests.fakes import FakeRequestStore


@pytest.fixture
def resources(tmp_path, monkeypatch):
    monkeypatch.setenv("ABI_API_KEY", "test-pipeline-key")
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path / 'catalog.sqlite'}",
            data_path=str(tmp_path / "warehouse") + "/",
        )
    )
    ensure_datasets(dataset)
    rows = DatasetRowStore(dataset)
    service = PipelineAppService(FakeRequestStore(), rows=rows)
    app = FastAPI()
    register(app, service)
    return (
        TestClient(app, headers={"Authorization": "Bearer test-pipeline-key"}),
        rows,
        service,
    )


def test_collection_edit_and_archive_do_not_change_queued_inputs(resources):
    client, rows, service = resources
    created = client.post(
        f"{PREFIX}/collections",
        json={
            "name": "Research",
            "locations": ["phases_v2/solitude", "phases_v2/ageing"],
        },
    )
    assert created.status_code == 201
    collection = created.json()
    path = f"{PREFIX}/collections/{collection['collection_id']}"
    request = service.submit_run(
        locations=collection["locations"],
        prompt_ids=[declared_prompts()[0].prompt_id],
        chunker_id=WINDOW_512_128.chunker_id,
        model_id=DECLARED_MODELS[0].model_id,
    )
    updated = client.put(path, json={"name": "Revised", "locations": ["phases_v2/new"]})
    assert updated.status_code == 200
    assert (
        client.get(f"{PREFIX}/collections").json()["collections"][0]["name"]
        == "Revised"
    )
    # A new service instance sees persisted edits.
    assert PipelineAppService(FakeRequestStore(), rows=rows).resources.collections()[0][
        "locations"
    ] == ["phases_v2/new"]
    assert client.delete(path).status_code == 200
    assert client.get(f"{PREFIX}/collections").json() == {"collections": []}
    assert (
        client.put(path, json={"name": "Gone", "locations": ["phases_v2"]}).status_code
        == 404
    )
    assert service.request(request.request_id)["locations"] == collection["locations"]


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "locations": ["phases_v2"]},
        {"name": "   ", "locations": ["phases_v2"]},
        {"name": "Empty", "locations": []},
        {"name": "Duplicate", "locations": ["phases_v2", "phases_v2"]},
        {"name": "Outside", "locations": ["another_module"]},
        {"name": "Traversal", "locations": ["phases_v2/../secrets"]},
        {"name": "Unexpected", "locations": ["phases_v2"], "extra": True},
    ],
)
def test_collection_validation_rejects_invalid_commands_before_writing(
    resources, payload
):
    client, rows, _ = resources
    assert client.post(f"{PREFIX}/collections", json=payload).status_code == 422
    assert rows.query("SELECT * FROM input_collections") == []


def test_collection_mutations_require_authentication(resources):
    client, _, _ = resources
    client.headers.clear()
    for method, path in [
        ("POST", "/collections"),
        ("PUT", "/collections/unknown"),
        ("DELETE", "/collections/unknown"),
    ]:
        response = client.request(
            method, PREFIX + path, json={"name": "Research", "locations": ["phases_v2"]}
        )
        assert response.status_code in (401, 403)
