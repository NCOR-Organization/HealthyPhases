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
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.store import ensure_datasets
from phases_v2.extraction.factory import resolve_prompt
from phases_v2.prompts.templates import declared_prompts
from phases_v2.requests.fakes import FakeRequestStore


@pytest.fixture
def resources(tmp_path):
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
    return TestClient(app), rows, service


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
        prompt_ids=["p"],
        chunker_id="c",
        model_id="m",
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


def test_prompt_edits_preserve_original_and_are_resolvable_by_the_worker(resources):
    client, rows, _ = resources
    original = declared_prompts()[0]
    first = client.post(
        f"{PREFIX}/prompts",
        json={
            "name": original.name,
            "template": "Custom claims: {chunk_text}",
            "output_key": original.output_key,
        },
    )
    assert first.status_code == 201
    second = client.post(
        f"{PREFIX}/prompts",
        json={
            "name": original.name,
            "template": "Revised claims: {chunk_text}",
            "output_key": original.output_key,
        },
    )
    assert second.status_code == 201
    assert first.json()["prompt_id"] != second.json()["prompt_id"]
    assert (
        resolve_prompt(first.json()["prompt_id"], rows).template
        == "Custom claims: {chunk_text}"
    )
    assert (
        resolve_prompt(second.json()["prompt_id"], rows).template
        == "Revised claims: {chunk_text}"
    )
    assert resolve_prompt(original.prompt_id, rows) == original
    assert {
        p["prompt_id"] for p in client.get(f"{PREFIX}/prompts").json()["prompts"]
    } >= {
        original.prompt_id,
        first.json()["prompt_id"],
        second.json()["prompt_id"],
    }


def test_prompt_schema_cannot_silently_change_under_an_existing_identity(resources):
    client, _, _ = resources
    first, other = declared_prompts()[:2]
    response = client.post(
        f"{PREFIX}/prompts",
        json={
            "name": first.name,
            "template": first.template,
            "output_key": other.output_key,
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"name": ""},
        {"template": "Missing placeholder"},
        {"output_key": "unknown"},
        {"template": 42},
        {"unexpected": True},
    ],
)
def test_prompt_contract_and_output_schema_are_validated(resources, changes):
    client, rows, _ = resources
    payload = {
        "name": "Custom",
        "template": "Extract {chunk_text}",
        "output_key": declared_prompts()[0].output_key,
    } | changes
    assert client.post(f"{PREFIX}/prompts", json=payload).status_code == 422
    assert rows.query("SELECT * FROM prompts") == []
