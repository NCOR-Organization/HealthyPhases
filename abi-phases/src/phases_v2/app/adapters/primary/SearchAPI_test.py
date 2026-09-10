from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from phases_v2.app.adapters.primary.SearchAPI import PREFIX, register
from phases_v2.search.contracts import canonical_items
from phases_v2.search.domain import SearchService
from phases_v2.search.fakes import FakeExtractedItems, FakeSemanticIndex


def _client() -> TestClient:
    items = canonical_items()
    service = SearchService(FakeSemanticIndex(items), FakeExtractedItems(items))
    app = FastAPI()
    register(app, service)
    return TestClient(app)


def test_semantic_endpoint_returns_located_hits():
    res = _client().get(f"{PREFIX}/semantic", params={"q": "stress", "k": 5})
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "semantic"
    assert body["count"] >= 1
    top = body["hits"][0]
    assert top["item_id"] == "item-effects"
    assert top["paper_name"] == "a.pdf"
    assert top["prompt_name"] == "solitude_effects"
    assert top["score"] is not None


def test_keyword_endpoint_requires_all_words():
    client = _client()
    one = client.get(f"{PREFIX}/keyword", params={"q": "solitude stress"})
    assert one.status_code == 200
    assert [h["item_id"] for h in one.json()["hits"]] == ["item-effects"]

    none = client.get(f"{PREFIX}/keyword", params={"q": "loneliness stress"})
    assert none.json()["count"] == 0


def test_keyword_endpoint_prompt_facet():
    res = _client().get(
        f"{PREFIX}/keyword", params=[("q", "isolation"), ("prompt", "solitude_causes")]
    )
    assert [h["item_id"] for h in res.json()["hits"]] == ["item-causes"]


def test_prompts_endpoint():
    res = _client().get(f"{PREFIX}/prompts")
    assert res.status_code == 200
    assert set(res.json()["prompts"]) >= {"solitude_causes", "solitude_effects"}
