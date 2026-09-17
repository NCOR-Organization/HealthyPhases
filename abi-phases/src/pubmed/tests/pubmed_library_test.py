from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pubmed.adapters.primary.pubmed_api import router
from pubmed.adapters.secondary.pubmed_dataset_store import PubmedDatasetStore
from pubmed.application.pubmed_service import PubmedService
from pubmed.tests.pubmed_service_test import FakeSource, MemoryStorage


@pytest.fixture
def library(dataset):
    store = PubmedDatasetStore(dataset)
    store.ensure()
    service = PubmedService(store, FakeSource(), MemoryStorage())
    first, second = str(uuid4()), str(uuid4())
    store.save(
        "queries",
        [
            {"query_id": q, "query": "solitude", "contract_version": 1}
            for q in (first, second)
        ],
    )
    store.save(
        "papers",
        [
            {
                "pmid": str(i),
                "pmcid": f"PMC{i}",
                "title": f"Paper {i:04d}",
                "journal": "Research Journal",
                "authors": ["O'Brien" if i == 1 else "Jane Doe"],
                "doi": f"10.1000/{i}",
                "publication_date": "2020 Jan",
            }
            for i in range(1, 1208)
        ],
    )
    store.save(
        "query_papers",
        [{"query_id": first, "pmid": str(i)} for i in range(1, 1208)]
        + [{"query_id": second, "pmid": "1"}],
    )
    artifacts = [
        {
            "artifact_id": f"{i}:pdf",
            "pmid": str(i),
            "pmcid": f"PMC{i}",
            "version": "1",
            "status": "ready",
            "storage_prefix": "pubmed/papers",
            "storage_key": f"PMC{i}/paper.pdf",
            "content_sha256": "a" * 64,
            "size_bytes": 10,
            "mime_type": "application/pdf",
            "source_url": "https://example.test/p.pdf",
            "published_at": f"2026-09-{15 if i <= 1000 else 16}T12:00:00+00:00",
            "contract_version": 1,
        }
        for i in range(1, 1206)
    ]
    store.save("artifacts", artifacts + [dict(artifacts[0], artifact_id="1:version2")])
    return service, first, second


def test_library_paginates_all_downloaded_papers_without_duplicate_versions(library):
    service, first, _ = library
    seen = []
    for page in range(1, 14):
        result = service.browse_papers({"page": page, "page_size": 100})
        assert result["total"] == 1205 and result["total_pages"] == 13
        seen.extend(p["paper"]["pmid"] for p in result["papers"])
    assert len(seen) == len(set(seen)) == 1205
    assert set(seen) == {str(i) for i in range(1, 1206)}
    assert len(result["papers"]) == 5
    past_end = service.browse_papers({"page": 999, "page_size": 100})
    assert past_end["papers"] == [] and past_end["total"] == 1205
    one = service.browse_papers(
        {"search": "10.1000/1", "query_id": first, "sort": "title"}
    )
    assert len(one["papers"][0]["artifacts"]) == 2


def test_library_filters_dates_status_query_and_literal_text(library):
    service, first, second = library
    result = service.browse_papers({"query_id": second, "search": "o'BRIEN"})
    assert result["total"] == 1 and result["papers"][0]["paper"]["pmid"] == "1"
    assert (
        service.browse_papers({"query_id": first, "search": "Research Journal"})[
            "total"
        ]
        == 1205
    )
    assert service.browse_papers({"search": "PMC1205"})["total"] == 1
    for search in ["%_", "' OR 1=1 --", "missing term"]:
        assert service.browse_papers({"search": search})["total"] == 0
    date_filters = {"ingested_from": "2026-09-16", "ingested_until": "2026-09-16"}
    assert service.browse_papers(date_filters)["total"] == 205
    assert service.browse_papers({"ingested_until": "2026-09-15"})["total"] == 1000
    assert service.browse_papers({"query_id": second, **date_filters})["total"] == 0
    assert service.browse_papers({"status": "all"})["total"] == 1207
    unpublished = service.browse_papers({"status": "unpublished"})
    assert unpublished["total"] == 2
    assert all(
        not p["artifacts"] and not p["last_ingested_at"] for p in unpublished["papers"]
    )
    oldest = service.browse_papers({"sort": "oldest", "page_size": 1})
    newest = service.browse_papers({"sort": "newest", "page_size": 1})
    assert (
        oldest["papers"][0]["last_ingested_at"]
        < newest["papers"][0]["last_ingested_at"]
    )


def test_library_http_validation_and_empty_results(library):
    service, _, second = library
    app = FastAPI()
    app.include_router(router(service))
    client = TestClient(app)
    response = client.get(
        "/pubmed/api/papers", params={"query_id": second, "page_size": 1}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["papers"][0]["paper"]["pmid"] == "1"
    for params in [
        {"page": 0},
        {"page_size": 101},
        {"page_size": -1},
        {"page": "bad"},
        {"status": "unknown"},
        {"sort": "title; DROP TABLE papers"},
        {"query_id": "bad"},
        {"search": "x" * 301},
        {"ingested_from": "2026-02-30"},
        {"ingested_from": "2026-09-17", "ingested_until": "2026-09-01"},
    ]:
        assert client.get("/pubmed/api/papers", params=params).status_code == 422
    assert (
        client.get("/pubmed/api/papers", params={"query_id": str(uuid4())}).status_code
        == 404
    )
    empty = client.get("/pubmed/api/papers", params={"search": "no such title"}).json()
    assert empty["total"] == empty["total_pages"] == 0 and empty["papers"] == []
