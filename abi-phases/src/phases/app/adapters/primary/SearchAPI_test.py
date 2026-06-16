from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from phases.app.adapters.primary.SearchAPI import register
from phases.app.contracts import canonical_items
from phases.app.domain import SearchService
from phases.app.fakes import FakeKnowledgeGraph, FakeSemanticIndex


def _client() -> TestClient:
    items = canonical_items()
    service = SearchService(FakeSemanticIndex(items), FakeKnowledgeGraph(items))
    app = FastAPI()
    register(app, service)
    return TestClient(app)


def test_semantic_endpoint_returns_located_hits():
    res = _client().get("/phases/api/search/semantic", params={"q": "stress", "k": 5})
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "semantic"
    assert body["count"] >= 1
    top = body["hits"][0]
    assert top["extracted_item_id"] == "item-effects"
    assert top["paper_name"] == "a.pdf"
    assert top["pipeline"] == "effects"
    assert top["score"] is not None


def test_keyword_endpoint_requires_all_words():
    client = _client()
    one = client.get("/phases/api/search/keyword", params={"q": "solitude stress"})
    assert one.status_code == 200
    assert [h["extracted_item_id"] for h in one.json()["hits"]] == ["item-effects"]

    none = client.get("/phases/api/search/keyword", params={"q": "loneliness stress"})
    assert none.json()["count"] == 0


def test_keyword_endpoint_pipeline_facet():
    res = _client().get(
        "/phases/api/search/keyword",
        params=[("q", "isolation"), ("pipeline", "causes")],
    )
    assert [h["extracted_item_id"] for h in res.json()["hits"]] == ["item-causes"]


def test_pipelines_endpoint():
    res = _client().get("/phases/api/pipelines")
    assert res.status_code == 200
    assert set(res.json()["pipelines"]) >= {"causes", "effects"}


def test_static_ui_served():
    res = _client().get("/phases/app/")
    assert res.status_code == 200
    assert "Reverse Search" in res.text
