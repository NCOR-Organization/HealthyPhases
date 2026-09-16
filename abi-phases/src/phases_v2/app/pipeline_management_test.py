"""Authoring and execution against real dataset and filesystem adapters."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService
from naas_abi_core.services.object_storage.adapters.secondary.ObjectStorageSecondaryAdapterFS import (
    ObjectStorageSecondaryAdapterFS,
)
from naas_abi_core.services.object_storage.ObjectStorageService import (
    ObjectStorageService,
)

from phases_v2.app.adapters.primary.PipelineAPI import PREFIX, register
from phases_v2.app.pipeline_management import MAX_UPLOAD_BYTES
from phases_v2.app.service import PipelineAppService
from phases_v2.chunking.chunkers import WINDOW_512_128
from phases_v2.chunking.factory import chunk_corpus
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.store import ensure_datasets
from phases_v2.extraction.factory import extract, resolve_prompt
from phases_v2.extraction.fakes import FakeModel
from phases_v2.identity import paper_id
from phases_v2.models.catalog import DECLARED_MODELS
from phases_v2.papers.adapters.secondary.PdfTextRenderer import PdfTextRenderer
from phases_v2.papers.factory import ingest_papers
from phases_v2.prompts.templates import declared_prompts
from phases_v2.requests.adapters.secondary.DatasetRequestStore import (
    DatasetRequestStore,
)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ABI_API_KEY", "test-pipeline-key")
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path / 'catalog.sqlite'}",
            data_path=str(tmp_path / "warehouse") + "/",
        )
    )
    ensure_datasets(dataset)
    rows = DatasetRowStore(dataset)
    storage = ObjectStorageService(
        adapter=ObjectStorageSecondaryAdapterFS(base_path=str(tmp_path / "objects"))
    )
    service = PipelineAppService(
        DatasetRequestStore(rows), storage, rows, renderer=PdfTextRenderer()
    )
    app = FastAPI()
    register(app, service)
    client = TestClient(app, headers={"Authorization": "Bearer test-pipeline-key"})
    engine = SimpleNamespace(
        services=SimpleNamespace(dataset=dataset, object_storage=storage)
    )
    yield service, client, engine
    client.close()


def inputs(prompt_id=None, locations=None):
    return {
        "locations": locations or ["phases_v2"],
        "chunker_id": WINDOW_512_128.chunker_id,
        "prompt_ids": [prompt_id or declared_prompts()[0].prompt_id],
        "model_id": DECLARED_MODELS[0].model_id,
    }


def pdf(text):
    import pymupdf

    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), text)
        return document.tobytes()


def test_prompt_versions_survive_service_restart_and_resolve_in_worker(environment):
    service, client, engine = environment
    payload = {
        "name": "Custom claims",
        "template": "Extract claims: {chunk_text}",
        "output_key": "results",
    }
    first = client.post(f"{PREFIX}/prompts", json=payload)
    assert first.status_code == 201
    first_id = first.json()["prompt_id"]
    second = client.post(
        f"{PREFIX}/prompts",
        json=payload | {"template": "Extract evidence: {chunk_text}"},
    ).json()
    assert second["prompt_id"] != first_id
    # Unchanged saves neither rewrite a historical row nor add another row.
    count = len(service.prompts())
    client.post(f"{PREFIX}/prompts", json=payload)
    assert len(service.prompts()) == count
    restarted = PipelineAppService(
        service._requests, rows=DatasetRowStore(engine.services.dataset)
    )
    assert {first_id, second["prompt_id"]} <= {
        p["prompt_id"] for p in restarted.prompts()
    }
    assert resolve_prompt(first_id, restarted._rows).template == payload["template"]
    conflict = client.post(f"{PREFIX}/prompts", json=payload | {"output_key": "what"})
    assert conflict.status_code == 422


@pytest.mark.parametrize(
    "change,field",
    [
        ({"template": "No placeholder"}, "template"),
        ({"output_key": "invented"}, "output_key"),
        ({"name": "../bad"}, "name"),
        ({"template": "x" * 100001 + "{chunk_text}"}, "template"),
    ],
)
def test_proto_validation_rejects_invalid_prompts(environment, change, field):
    service, client, _ = environment
    count = len(service.prompts())
    response = client.post(
        f"{PREFIX}/prompts",
        json={"name": "Claims", "template": "{chunk_text}", "output_key": "results"}
        | change,
    )
    assert response.status_code == 422
    assert field in response.json()["detail"]
    assert len(service.prompts()) == count


def test_empty_collection_survives_restart_and_accepts_uploads(environment):
    service, client, _ = environment
    response = client.post(f"{PREFIX}/locations", json={"name": "Sleep studies"})
    assert response.status_code == 201
    prefix = response.json()["prefix"]
    assert response.json() in service.locations()
    assert service.documents([prefix])["total"] == 0
    restarted = PipelineAppService(service._requests, service._storage, service._rows)
    assert response.json() in restarted.locations()
    content = pdf("Sleep evidence")
    response = client.post(
        f"{PREFIX}/documents",
        params={"location": prefix, "filename": "study.pdf"},
        content=content,
    )
    assert response.status_code == 201
    assert service.documents([prefix])["ingestable"] == 1


def test_uploads_preserve_same_named_documents_and_retry_idempotently(environment):
    service, client, _ = environment

    def upload(content):
        return client.post(
            f"{PREFIX}/documents",
            params={"location": "phases_v2", "filename": "study.pdf"},
            content=content,
        )

    content_a, content_b = pdf("Evidence A"), pdf("Evidence B")
    first, second = upload(content_a), upload(content_b)
    assert first.status_code == second.status_code == 201
    assert first.json()["key"] != second.json()["key"]
    assert upload(content_a).json()["key"] == first.json()["key"]
    assert service.documents(["phases_v2"])["total"] == 2


@pytest.mark.parametrize(
    "location,filename,content",
    [
        ("phases_v2/../private", "a.pdf", b"%PDF-valid"),
        ("other_module", "a.pdf", b"%PDF-valid"),
        ("phases_v2", "../a.pdf", b"%PDF-valid"),
        ("phases_v2", "a.txt", b"%PDF-valid"),
        ("phases_v2", "a.pdf", b"not a PDF"),
    ],
)
def test_invalid_upload_never_writes(environment, location, filename, content):
    service, client, _ = environment
    response = client.post(
        f"{PREFIX}/documents",
        params={"location": location, "filename": filename},
        content=content,
    )
    assert response.status_code == 422
    assert service.documents(["phases_v2"])["total"] == 0


def test_upload_size_is_limited_before_storage(environment):
    service, client, _ = environment
    response = client.post(
        f"{PREFIX}/documents",
        params={"location": "phases_v2", "filename": "a.pdf"},
        content=b"%PDF-" + b"x" * MAX_UPLOAD_BYTES,
    )
    assert response.status_code == 413
    assert service.documents(["phases_v2"])["total"] == 0


def test_write_endpoints_require_authentication(environment):
    _, client, _ = environment
    client.headers.pop("Authorization")
    for endpoint in (
        "prompts",
        "locations",
        "documents",
        "pipelines",
        "pipelines/abc/requests",
    ):
        assert client.post(f"{PREFIX}/{endpoint}", json={}).status_code == 401


def test_saved_pipeline_keeps_exact_prompt_version_and_runs_after_restart(environment):
    service, client, _ = environment
    first = service.management.save_prompt(
        {"name": "Custom", "template": "First {chunk_text}", "output_key": "results"}
    )
    original_inputs = inputs(first["prompt_id"])
    pipeline = client.post(
        f"{PREFIX}/pipelines",
        json={"name": "Sleep research", "inputs": original_inputs},
    )
    assert pipeline.status_code == 201
    pipeline_id = pipeline.json()["pipeline_id"]
    service.management.save_prompt(
        {"name": "Custom", "template": "Second {chunk_text}", "output_key": "results"}
    )
    restarted = PipelineAppService(service._requests, service._storage, service._rows)
    assert restarted.management.pipeline(pipeline_id)["inputs"] == original_inputs
    response = client.post(f"{PREFIX}/pipelines/{pipeline_id}/requests")
    assert response.status_code == 201
    request = service.request(response.json()["request_id"])
    assert request["prompt_ids"] == original_inputs["prompt_ids"]
    assert request["status"] == "pending"


@pytest.mark.parametrize(
    "change",
    [
        {"prompt_ids": ["unknown"]},
        {"model_id": "unknown"},
        {"chunker_id": "unknown"},
        {"locations": ["private"]},
    ],
)
def test_invalid_saved_inputs_are_refused_before_queueing(environment, change):
    _, client, _ = environment
    assert client.post(f"{PREFIX}/requests", json=inputs() | change).status_code == 422
    assert client.get(f"{PREFIX}/requests").json()["requests"] == []


def test_uploaded_collection_extracts_only_its_content_with_a_custom_prompt(
    environment,
):
    service, _, engine = environment
    prompt = service.management.save_prompt(
        {"name": "Custom", "template": "Claims {chunk_text}", "output_key": "results"}
    )
    target, unrelated = pdf("Target evidence"), pdf("Unrelated evidence")
    service.management.upload("phases_v2/target", "same.pdf", target)
    service.management.upload("phases_v2/other", "same.pdf", unrelated)
    # Pre-ingest everything to cover reusing already-ingested documents.
    ingest_papers(engine, ["phases_v2"])
    selected = ingest_papers(engine, ["phases_v2/target"])
    assert selected.paper_ids == [paper_id(target)]
    assert selected.skipped == 1
    chunk_corpus(engine, paper_ids=selected.paper_ids)
    model = FakeModel()
    report = extract(
        engine,
        model_id=DECLARED_MODELS[0].model_id,
        prompt_id=prompt["prompt_id"],
        paper_ids=selected.paper_ids,
        model=model,
    )
    assert report.succeeded > 0
    assert all("Unrelated" not in text for text in model.prompts)
    assert {
        row["paper_id"] for row in service._rows.query("SELECT paper_id FROM chunks")
    } == {paper_id(target)}
    model.prompts.clear()
    assert (
        extract(
            engine,
            model_id=DECLARED_MODELS[0].model_id,
            prompt_id=prompt["prompt_id"],
            paper_ids=[],
            model=model,
        ).executed
        == 0
    )
    assert not model.prompts


def test_uploaded_document_preview_uses_content_identity_not_filename(environment):
    service, _, engine = environment
    first, second = pdf("First content"), pdf("Second content")
    service.management.upload("phases_v2/first", "study.pdf", first)
    ingest_papers(engine, ["phases_v2/first"])
    service.management.upload("phases_v2/second", "study.pdf", second)
    assert service.documents(["phases_v2/second"])["already_ingested"] == 0
    service.management.upload("phases_v2/second", "copy.pdf", first)
    assert service.documents(["phases_v2/second"])["already_ingested"] == 1
    preview = service.documents(["phases_v2", "phases_v2/second"])
    assert preview["total"] == 3


def test_storage_failure_is_reported_without_claiming_upload_success(
    environment, monkeypatch
):
    service, client, _ = environment

    def fail(*args):
        raise OSError("storage offline")

    monkeypatch.setattr(service._storage, "put_object", fail)
    response = client.post(
        f"{PREFIX}/documents",
        params={"location": "phases_v2", "filename": "a.pdf"},
        content=b"%PDF-1.4",
    )
    assert response.status_code == 503
