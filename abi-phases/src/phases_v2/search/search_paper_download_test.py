"""Source downloads through real SQL joins and the HTTP adapter."""

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from naas_abi_core.services.object_storage.ObjectStoragePort import Exceptions

from phases_v2.app.adapters.primary.SearchAPI import PREFIX, register
from phases_v2.search.adapters.secondary.DatasetExtractedItemsAdapter import (
    DatasetExtractedItemsAdapter,
)
from phases_v2.search.domain import SearchService
from phases_v2.search.fakes import FakeSemanticIndex

PDF = b"%PDF-1.7\noriginal paper bytes"


class Rows:
    def __init__(self, prefix, key):
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE extracted_items(item_id TEXT, paper_id TEXT);
            CREATE TABLE papers(paper_id TEXT, storage_prefix TEXT, storage_key TEXT, file_name TEXT);
            INSERT INTO extracted_items VALUES ('item', 'paper');
        """)
        self.connection.execute(
            "INSERT INTO papers VALUES (?, ?, ?, ?)",
            ("paper", prefix, key, "paper.pdf"),
        )

    def query(self, sql):
        return [dict(row) for row in self.connection.execute(sql)]


class Storage:
    def __init__(self, content=PDF, error=None):
        self.content, self.error = content, error
        self.calls = []

    def get_object(self, prefix, key):
        self.calls.append((prefix, key))
        if self.error:
            raise self.error
        return self.content


def client(
    prefix="phases_v2/stress",
    key="papers/Research paper.pdf",
    storage=None,
    root="phases_v2",
):
    storage = storage if storage is not None else Storage()
    rows = Rows(prefix, key)
    adapter = DatasetExtractedItemsAdapter(rows, storage, root)
    app = FastAPI()
    register(app, SearchService(FakeSemanticIndex(), adapter))
    return TestClient(app), storage


def test_original_object_is_downloaded_as_a_pdf_attachment():
    api, storage = client()
    response = api.get(f"{PREFIX}/paper", params={"item_id": "item"})
    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert (
        response.headers["content-disposition"]
        == "attachment; filename*=UTF-8''Research%20paper.pdf"
    )
    assert storage.calls == [("phases_v2/stress", "papers/Research paper.pdf")]


@pytest.mark.parametrize(
    "prefix,key",
    [
        ("private", "paper.pdf"),
        ("phases_v2-other", "paper.pdf"),
        ("phases_v2/../private", "paper.pdf"),
        ("phases_v2", "../paper.pdf"),
        ("/phases_v2", "paper.pdf"),
        ("phases_v2", "/paper.pdf"),
        ("phases_v2", "notes.txt"),
        ("phases_v2", "../private\\paper.pdf"),
        ("phases_v2", ""),
        (None, None),
    ],
)
def test_unsafe_or_missing_object_addresses_are_never_read(prefix, key):
    api, storage = client(prefix, key)
    assert api.get(f"{PREFIX}/paper", params={"item_id": "item"}).status_code == 404
    assert storage.calls == []


@pytest.mark.parametrize(
    "item_id", ["missing", "item' OR 1=1 --", "phases_v2/paper.pdf"]
)
def test_request_must_identify_an_existing_extracted_item(item_id):
    api, storage = client()
    assert api.get(f"{PREFIX}/paper", params={"item_id": item_id}).status_code == 404
    assert storage.calls == []


@pytest.mark.parametrize("item_id", ["", "a" * 201])
def test_download_request_executes_protovalidate_rules(item_id):
    api, storage = client()
    assert api.get(f"{PREFIX}/paper", params={"item_id": item_id}).status_code == 422
    assert storage.calls == []


@pytest.mark.parametrize(
    "storage",
    [Storage(content=b"not PDF"), Storage(error=Exceptions.ObjectNotFound("missing"))],
)
def test_missing_or_invalid_pdf_returns_clear_404(storage):
    api, _ = client(storage=storage)
    response = api.get(f"{PREFIX}/paper", params={"item_id": "item"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Source PDF is unavailable."


def test_backend_failure_is_not_reported_as_missing_paper():
    api, _ = client(storage=Storage(error=RuntimeError("private backend error")))
    response = api.get(f"{PREFIX}/paper", params={"item_id": "item"})
    assert response.status_code == 503
    assert "private backend" not in response.text


def test_configured_corpus_root_is_supported():
    api, storage = client(prefix="research/stress", root="research")
    assert api.get(f"{PREFIX}/paper", params={"item_id": "item"}).status_code == 200
    assert storage.calls[0][0] == "research/stress"
