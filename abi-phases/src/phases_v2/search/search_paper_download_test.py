"""Source downloads through real SQL joins and the HTTP adapter."""

import hashlib
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
PDF_SHA = hashlib.sha256(PDF).hexdigest()


class Rows:
    def __init__(self, prefix, key, sha256=PDF_SHA):
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE extracted_items(item_id TEXT, paper_id TEXT);
            CREATE TABLE papers(paper_id TEXT, storage_prefix TEXT, storage_key TEXT,
                file_name TEXT, content_sha256 TEXT);
            INSERT INTO extracted_items VALUES ('item', 'paper');
        """)
        self.connection.execute(
            "INSERT INTO papers VALUES (?, ?, ?, ?, ?)",
            ("paper", prefix, key, "paper.pdf", sha256),
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
    published=None,
    sha256=PDF_SHA,
):
    storage = storage if storage is not None else Storage()
    rows = Rows(prefix, key, sha256)
    adapter = DatasetExtractedItemsAdapter(rows, storage, root, published)
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


def test_a_papers_own_pdf_is_downloaded_by_its_id():
    api, storage = client()
    response = api.get(f"{PREFIX}/paper", params={"paper_id": "paper"})
    assert response.status_code == 200
    assert response.content == PDF
    assert storage.calls == [("phases_v2/stress", "papers/Research paper.pdf")]


@pytest.mark.parametrize(
    "prefix,key", [("private", "paper.pdf"), ("phases_v2", "../paper.pdf")]
)
def test_a_paper_named_by_id_is_held_to_the_same_address_rules(prefix, key):
    api, storage = client(prefix, key)
    assert api.get(f"{PREFIX}/paper", params={"paper_id": "paper"}).status_code == 404
    assert storage.calls == []


@pytest.mark.parametrize(
    "params",
    [{}, {"item_id": "item", "paper_id": "paper"}, {"paper_id": "a" * 201}],
)
def test_a_download_names_exactly_one_hit_or_paper(params):
    api, storage = client()
    assert api.get(f"{PREFIX}/paper", params=params).status_code == 422
    assert storage.calls == []


def test_an_unknown_paper_id_is_a_404():
    api, storage = client()
    response = api.get(f"{PREFIX}/paper", params={"paper_id": "paper' OR 1=1 --"})
    assert response.status_code == 404
    assert storage.calls == []


class Published:
    """Stands in for the PubMed artifacts table: these objects were published."""

    def __init__(self, *objects):
        self.objects = set(objects)
        self.asked = []

    def __call__(self, prefix, key, sha256):
        self.asked.append((prefix, key, sha256))
        return (prefix, key, sha256) in self.objects


PUBMED_KEY = ("pubmed/papers", f"PMC1/{PDF_SHA}.pdf")


def test_a_published_pubmed_pdf_is_served_from_outside_the_papers_root():
    published = Published((*PUBMED_KEY, PDF_SHA))
    api, storage = client(*PUBMED_KEY, published=published)

    for params in ({"paper_id": "paper"}, {"item_id": "item"}):
        response = api.get(f"{PREFIX}/paper", params=params)
        assert response.status_code == 200
        assert response.content == PDF
    assert storage.calls == [PUBMED_KEY, PUBMED_KEY]


@pytest.mark.parametrize(
    "published",
    [
        None,
        # Published, but under another hash than the paper's.
        Published((*PUBMED_KEY, "f" * 64)),
        Published(),
    ],
)
def test_outside_the_root_only_a_published_artifact_is_read(published):
    api, storage = client(*PUBMED_KEY, published=published)
    assert api.get(f"{PREFIX}/paper", params={"paper_id": "paper"}).status_code == 404
    assert storage.calls == []


def test_a_published_pdf_whose_bytes_changed_is_not_served():
    published = Published((*PUBMED_KEY, "e" * 64))
    api, storage = client(*PUBMED_KEY, published=published, sha256="e" * 64)
    response = api.get(f"{PREFIX}/paper", params={"paper_id": "paper"})
    assert response.status_code == 404
    assert storage.calls == [PUBMED_KEY]


def test_a_published_pdf_still_obeys_the_address_rules():
    key = ("pubmed/papers", "../secret.pdf")
    published = Published((*key, PDF_SHA))
    api, storage = client(*key, published=published)
    assert api.get(f"{PREFIX}/paper", params={"paper_id": "paper"}).status_code == 404
    assert storage.calls == [] and published.asked == []


def test_naming_both_a_hit_and_a_paper_says_so():
    api, _ = client()
    response = api.get(
        f"{PREFIX}/paper", params={"item_id": "item", "paper_id": "paper"}
    )
    assert response.json()["detail"] == "Give an item_id or a paper_id, not both."
