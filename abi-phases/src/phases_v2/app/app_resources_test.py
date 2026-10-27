"""Collections of papers, through the HTTP boundary, on real datasets.

The PubMed publisher runs for real against the same dataset service, so a
saved search member resolves through the catalog exactly as it does deployed.
"""

from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService
from naas_abi_core.services.object_storage.ObjectStoragePort import (
    Exceptions as StorageExceptions,
)

from phases_v2.app.adapters.primary.PipelineAPI import PREFIX, register
from phases_v2.app.service import PipelineAppService
from phases_v2.chunking.chunkers import WINDOW_512_128
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.store import ensure_datasets
from phases_v2.models.catalog import DECLARED_MODELS
from phases_v2.paper_collections.adapters.secondary.StoredMemberSources import (
    StoredMemberSources,
)
from phases_v2.prompts.templates import declared_prompts
from phases_v2.requests.fakes import FakeRequestStore
from phases_v2.sources.adapters.secondary.phases_v2_pubmed_catalog import PubmedCatalog
from phases_v2.sources.phases_v2_sources import manifest_for
from pubmed.adapters.secondary.pubmed_dataset_store import PubmedDatasetStore
from pubmed.application.pubmed_service import PubmedService
from pubmed.tests.pubmed_service_test import FakeSource, MemoryStorage, queue

FOLDER_PDF = b"%PDF-1.7 a folder document"
INGESTED_PDF = b"%PDF-1.7 ingested before"


class Storage(MemoryStorage):
    """Object storage that also lists, as the engine's service does."""

    def __init__(self):
        super().__init__()
        self.unreachable = set()

    def list_objects_recursive(self, prefix):
        if prefix in self.unreachable:
            raise RuntimeError("storage timed out")
        keys = [
            f"{p}/{k}" for p, k in self.files if f"{p}/{k}".startswith(prefix + "/")
        ]
        if not keys:
            raise StorageExceptions.ObjectNotFound(prefix)
        return keys


class PdfOnly:
    def handles(self, name):
        return name.lower().endswith(".pdf")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ABI_API_KEY", "test-pipeline-key")
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path / 'catalog.sqlite'}",
            data_path=str(tmp_path / "warehouse") + "/",
        )
    )
    store = PubmedDatasetStore(dataset)
    store.ensure()
    storage = Storage()
    publisher = PubmedService(store, FakeSource(), storage)
    published = queue(publisher)
    publisher.execute(published["request_id"], "run")
    ensure_datasets(dataset)
    rows = DatasetRowStore(dataset)

    storage.put_object("phases_v2/mine", "a.pdf", FOLDER_PDF)
    storage.put_object("phases_v2/mine", "notes.txt", b"not a paper")
    storage.put_object("phases_v2/elsewhere", "unrelated.pdf", b"%PDF-1.7 other")
    ingested = sha256(INGESTED_PDF).hexdigest()
    storage.put_object("phases_v2/old", "x.pdf", INGESTED_PDF)
    rows.write_rows(
        "papers",
        [
            {
                "paper_id": ingested,
                "storage_prefix": "phases_v2/old",
                "storage_key": "x.pdf",
                "file_name": "x.pdf",
                "content_sha256": ingested,
                "text_key": f"{ingested}.md",
            }
        ],
    )
    rows.write_rows(
        "extracted_items",
        [{"item_id": "item-1", "paper_id": ingested, "text": "Solitude helps."}],
    )

    requests = FakeRequestStore()
    pubmed = PubmedCatalog(dataset)
    service = PipelineAppService(
        requests,
        object_storage=storage,
        rows=rows,
        pubmed_catalog=pubmed,
        collection_sources=StoredMemberSources(rows, storage, pubmed),
        renderer=PdfOnly(),
    )
    app = FastAPI()
    register(app, service)
    client = TestClient(app, headers={"Authorization": "Bearer test-pipeline-key"})
    return SimpleNamespace(
        client=client,
        rows=rows,
        service=service,
        storage=storage,
        requests=requests,
        dataset=dataset,
        publisher=publisher,
        query_id=published["query_id"],
        artifacts=PubmedCatalog(dataset).artifacts(published["query_id"]),
        ingested=ingested,
    )


def run_choices():
    return {
        "chunker_id": WINDOW_512_128.chunker_id,
        "prompt_ids": [declared_prompts()[0].prompt_id],
        "model_id": DECLARED_MODELS[0].model_id,
    }


def create(env, **body):
    response = env.client.post(f"{PREFIX}/collections", json={"name": "Mixed", **body})
    assert response.status_code == 201, response.text
    return response.json()


def detail(env, collection_id):
    response = env.client.get(f"{PREFIX}/collections/{collection_id}")
    assert response.status_code == 200, response.text
    return response.json()


# -- what a collection holds -------------------------------------------


def test_a_mixed_collection_lists_each_paper_once_with_its_status(env):
    collection = create(
        env,
        description="All four ways",
        members=[
            {"pubmed_query": {"query_id": env.query_id}},
            {"paper": {"pmid": "1"}},
            {"paper": {"paper_id": env.ingested}},
            {"folder": {"prefix": "phases_v2/mine"}},
        ],
    )
    # The same PDF as PubMed paper 1, uploaded into the collection.
    pubmed_one = env.storage.get_object(
        env.artifacts[0]["storage_prefix"], env.artifacts[0]["storage_key"]
    )
    uploaded = env.client.post(
        f"{PREFIX}/collections/{collection['collection_id']}/documents",
        params={"filename": "copy.pdf"},
        content=pubmed_one,
    )
    assert uploaded.status_code == 201, uploaded.text

    shown = detail(env, collection["collection_id"])

    assert shown["description"] == "All four ways"
    assert shown["paper_count"] == 4
    by_name = {paper["name"]: paper for paper in shown["papers"]}
    assert set(by_name) == {"Paper 1", "Paper 2", "x.pdf", "a.pdf"}
    assert by_name["x.pdf"]["status"] == "results"
    assert by_name["x.pdf"]["results"] == 1
    assert by_name["a.pdf"]["status"] == "not_ingested"
    assert by_name["a.pdf"]["paper_id"] is None
    assert by_name["Paper 1"]["pmid"] == "1"
    assert shown["status_counts"] == {"not_ingested": 3, "ingested": 0, "results": 1}
    assert shown["unsupported"] == 1
    kinds = [(m["kind"], m["label"], m["paper_count"]) for m in shown["members"]]
    assert kinds == [
        ("pubmed_query", "solitude", 2),
        ("paper", "Paper 1", 1),
        ("paper", "x.pdf", 1),
        ("folder", "phases_v2/mine", 1),
        ("folder", "Mixed uploads", 1),
    ]
    assert shown["members"][-1]["uploads"] is True

    listed = env.client.get(f"{PREFIX}/collections").json()["collections"]
    assert [(c["name"], c["member_count"], c["paper_count"]) for c in listed] == [
        ("Mixed", 5, 4)
    ]
    assert listed[0]["updated_at"] >= listed[0]["created_at"]


def test_papers_newly_published_for_a_member_search_join_by_themselves(env):
    collection = create(env, members=[{"pubmed_query": {"query_id": env.query_id}}])
    assert detail(env, collection["collection_id"])["paper_count"] == 2

    artifact = env.publisher.store.rows("artifacts")[0]
    env.publisher.store.save(
        "artifacts",
        [
            dict(
                artifact,
                artifact_id="later-version",
                storage_key="later.pdf",
                content_sha256="f" * 64,
            )
        ],
    )

    assert detail(env, collection["collection_id"])["paper_count"] == 3


def test_a_second_upload_reuses_the_collection_folder(env):
    collection = create(env)
    path = f"{PREFIX}/collections/{collection['collection_id']}/documents"
    for name in ("one.pdf", "two.pdf"):
        response = env.client.post(
            path, params={"filename": name}, content=b"%PDF-1.7 " + name.encode()
        )
        assert response.status_code == 201
    refused = env.client.post(path, params={"filename": "x.pdf"}, content=b"text")
    assert refused.status_code == 422

    shown = detail(env, collection["collection_id"])
    assert [m["kind"] for m in shown["members"]] == ["folder"]
    assert shown["paper_count"] == 2
    prefix = f"phases_v2/collections/{collection['collection_id']}"
    assert {"prefix": prefix, "name": "Mixed uploads"} in env.client.get(
        f"{PREFIX}/locations"
    ).json()["locations"]


def test_an_ingested_paper_can_be_found_to_be_picked(env):
    found = env.client.get(f"{PREFIX}/papers", params={"q": "X.P"}).json()["papers"]

    assert [(p["paper_id"], p["path"]) for p in found] == [
        (env.ingested, "phases_v2/old/x.pdf")
    ]
    assert env.client.get(f"{PREFIX}/papers", params={"q": "nothing"}).json() == {
        "papers": []
    }


# -- legacy collections ------------------------------------------------


def test_folder_collections_stored_before_still_list_edit_and_run(env):
    legacy_id = str(uuid4())
    env.rows.write_rows(
        "input_collections",
        [
            {
                "collection_id": legacy_id,
                "name": "Old folders",
                "locations": ["phases_v2/mine"],
                "archived": False,
            },
            {
                "collection_id": str(uuid4()),
                "name": "Archived before",
                "locations": ["phases_v2"],
                "archived": True,
            },
        ],
    )

    [listed] = env.client.get(f"{PREFIX}/collections").json()["collections"]
    assert listed["name"] == "Old folders"
    assert listed["locations"] == ["phases_v2/mine"]
    assert listed["description"] == ""
    assert listed["paper_count"] == 1

    renamed = env.client.put(
        f"{PREFIX}/collections/{legacy_id}",
        json={"name": "Renamed", "description": "Now described"},
    )
    assert renamed.status_code == 200, renamed.text
    [listed] = env.client.get(f"{PREFIX}/collections").json()["collections"]
    assert (listed["collection_id"], listed["name"]) == (legacy_id, "Renamed")
    assert listed["locations"] == ["phases_v2/mine"]
    # The first row is kept as it was; the edit lives in the new dataset.
    assert env.rows.query(
        "SELECT name FROM input_collections WHERE archived = false"
    ) == [{"name": "Old folders"}]

    submitted = env.client.post(
        f"{PREFIX}/requests", json={"collection_id": legacy_id, **run_choices()}
    )
    assert submitted.status_code == 201, submitted.text
    manifest = manifest_for(env.rows, submitted.json()["request_id"])
    assert [(a["storage_prefix"], a["storage_key"]) for a in manifest] == [
        ("phases_v2/mine", "a.pdf")
    ]


def test_creating_from_folders_alone_still_works(env):
    collection = create(env, locations=["phases_v2/mine", "phases_v2/old/"])

    assert collection["locations"] == ["phases_v2/mine", "phases_v2/old"]
    assert detail(env, collection["collection_id"])["paper_count"] == 2


# -- runs --------------------------------------------------------------


def test_a_run_on_a_collection_ingests_exactly_its_resolved_papers(env, monkeypatch):
    from phases_v2.papers.adapters.secondary.PdfTextRenderer import PdfTextRenderer
    from phases_v2.papers.factory import ingest_papers

    collection = create(
        env,
        members=[
            {"paper": {"pmid": "2"}},
            {"folder": {"prefix": "phases_v2/mine"}},
            {"paper": {"paper_id": env.ingested}},
        ],
    )
    submitted = env.client.post(
        f"{PREFIX}/requests",
        json={"collection_id": collection["collection_id"], **run_choices()},
    )
    assert submitted.status_code == 201, submitted.text
    request_id = submitted.json()["request_id"]
    request = env.client.get(f"{PREFIX}/requests/{request_id}").json()
    assert request["locations"] == [f"dataset:collection:{collection['collection_id']}"]
    assert request["collection"] == {
        "collection_id": collection["collection_id"],
        "name": "Mixed",
        "archived": False,
    }

    manifest = manifest_for(env.rows, request_id)
    monkeypatch.setattr(PdfTextRenderer, "render", lambda self, content, name: "Text")
    engine = SimpleNamespace(
        services=SimpleNamespace(dataset=env.dataset, object_storage=env.storage)
    )
    report = ingest_papers(
        engine, sorted({a["storage_prefix"] for a in manifest}), artifacts=manifest
    )

    assert report.failed == 0
    assert sorted(report.paper_ids) == sorted(
        [
            env.artifacts[1]["content_sha256"],
            sha256(FOLDER_PDF).hexdigest(),
            env.ingested,
        ]
    )

    # Later changes to the collection do not change what was submitted.
    env.client.delete(f"{PREFIX}/collections/{collection['collection_id']}")
    assert manifest_for(env.rows, request_id) == manifest
    [listed] = env.client.get(f"{PREFIX}/requests").json()["requests"]
    assert listed["collection"]["name"] == "Mixed"
    assert listed["collection"]["archived"] is True


def test_an_empty_collection_cannot_be_run(env):
    collection = create(env, members=[{"folder": {"prefix": "phases_v2/nothing"}}])

    response = env.client.post(
        f"{PREFIX}/requests",
        json={"collection_id": collection["collection_id"], **run_choices()},
    )

    assert response.status_code == 422
    assert "no papers yet" in response.json()["detail"]
    assert env.requests.pending() == []
    assert env.rows.query("SELECT * FROM source_manifests") == []


def test_a_collection_with_an_unreadable_member_is_not_run_partly(env):
    collection = create(
        env,
        members=[
            {"folder": {"prefix": "phases_v2/mine"}},
            {"folder": {"prefix": "phases_v2/old"}},
        ],
    )
    env.storage.unreachable.add("phases_v2/old")

    shown = detail(env, collection["collection_id"])
    assert shown["paper_count"] == 1
    assert "storage timed out" in shown["members"][1]["error"]
    response = env.client.post(
        f"{PREFIX}/requests",
        json={"collection_id": collection["collection_id"], **run_choices()},
    )

    assert response.status_code == 422
    assert "could not be read" in response.json()["detail"]
    assert env.requests.pending() == []


def test_a_saved_configuration_can_target_a_collection(env):
    collection = create(env, members=[{"pubmed_query": {"query_id": env.query_id}}])
    inputs = {"collection_id": collection["collection_id"], **run_choices()}
    saved = env.client.post(
        f"{PREFIX}/pipelines", json={"name": "On mixed", "inputs": inputs}
    )
    assert saved.status_code == 201, saved.text

    queued = env.client.post(
        f"{PREFIX}/pipelines/{saved.json()['pipeline_id']}/requests"
    )

    assert queued.status_code == 201, queued.text
    assert len(manifest_for(env.rows, queued.json()["request_id"])) == 2


def test_run_inputs_name_folders_or_one_existing_collection(env):
    collection = create(env, members=[{"folder": {"prefix": "phases_v2/mine"}}])
    cases = [
        # Folders and a collection at once is ambiguous.
        (
            {
                "locations": ["phases_v2/mine"],
                "collection_id": collection["collection_id"],
            },
            422,
        ),
        # Neither says what to run on.
        ({}, 422),
        ({"collection_id": "00000000-0000-4000-8000-000000000000"}, 404),
        ({"collection_id": "not-a-collection-id"}, 422),
    ]
    for inputs, status in cases:
        body = {**inputs, **run_choices()}
        assert env.client.post(f"{PREFIX}/requests", json=body).status_code == status
        saved = env.client.post(
            f"{PREFIX}/pipelines", json={"name": "X", "inputs": body}
        )
        assert saved.status_code == status, inputs
    assert env.requests.pending() == []


# -- changing a collection ---------------------------------------------


def test_members_are_added_once_and_can_be_removed(env):
    collection = create(env)
    path = f"{PREFIX}/collections/{collection['collection_id']}"
    for _ in range(2):
        added = env.client.post(
            f"{path}/members", json={"members": [{"paper": {"pmid": "1"}}]}
        )
        assert added.status_code == 200, added.text
    [member] = added.json()["members"]

    removed = env.client.delete(f"{path}/members/{member['member_id']}")
    assert removed.status_code == 200
    assert removed.json()["members"] == []
    again = env.client.delete(f"{path}/members/{member['member_id']}")
    assert again.status_code == 404
    assert again.json()["detail"] == "That member is no longer in this collection."


def test_an_archived_collection_leaves_lists_and_cannot_be_changed(env):
    collection = create(env)
    path = f"{PREFIX}/collections/{collection['collection_id']}"

    assert env.client.delete(path).status_code == 200

    assert env.client.get(f"{PREFIX}/collections").json() == {"collections": []}
    for method, url, body in [
        ("GET", path, None),
        ("PUT", path, {"name": "Back"}),
        ("POST", f"{path}/members", {"members": [{"paper": {"pmid": "1"}}]}),
        ("DELETE", path, None),
    ]:
        response = env.client.request(method, url, json=body)
        assert response.status_code == 404
        assert "may have been archived" in response.json()["detail"]


INVALID = [
    ({"name": ""}, "name"),
    ({"name": "   "}, "name"),
    ({"name": "Extra", "extra": True}, "extra"),
    ({"name": "X", "members": [{}]}, "members[0].member"),
    ({"name": "X", "members": [{"paper": {"pmid": "PMC1"}}]}, "pmid"),
    ({"name": "X", "members": [{"folder": {"prefix": "other_module"}}]}, "inside"),
    (
        {"name": "X", "members": [{"folder": {"prefix": "phases_v2/../secret"}}]},
        "inside",
    ),
    (
        {"name": "X", "members": [{"pubmed_query": {"query_id": str(uuid4())}}]},
        "no longer exists",
    ),
    ({"name": "X", "members": [{"paper": {"pmid": "999"}}]}, "no downloaded PDF"),
    (
        {"name": "X", "members": [{"paper": {"paper_id": "e" * 64}}]},
        "not been ingested",
    ),
    ({"name": "X", "locations": ["phases_v2", "phases_v2"]}, "unique"),
]


def test_invalid_collections_are_refused_with_the_reason_before_writing(env):
    for payload, message in INVALID:
        response = env.client.post(f"{PREFIX}/collections", json=payload)

        assert response.status_code == 422, payload
        assert message in response.json()["detail"], payload
    assert env.rows.query("SELECT * FROM paper_collections") == []


def test_collection_changes_require_authentication(env):
    env.client.headers.clear()
    for method, path in [
        ("POST", "/collections"),
        ("PUT", "/collections/unknown"),
        ("DELETE", "/collections/unknown"),
        ("POST", "/collections/unknown/members"),
        ("DELETE", "/collections/unknown/members/m"),
        ("POST", "/collections/unknown/documents?filename=a.pdf"),
    ]:
        response = env.client.request(method, PREFIX + path, json={"name": "X"})
        assert response.status_code in (401, 403), (method, path)
