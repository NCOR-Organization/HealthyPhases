from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from phases_v2.app.adapters.primary.SearchAPI import PREFIX, register
from phases_v2.search.contracts import canonical_items
from phases_v2.search.domain import SearchService
from phases_v2.search.fakes import FakeExtractedItems, FakeSemanticIndex


def _client() -> TestClient:
    items = canonical_items()
    items[1].location = replace(
        items[1].location, model_id="openrouter/claude-sonnet-4.6"
    )
    items[0].location = replace(
        items[0].location,
        source_path="phases_v2/solitude/paid",
        prompt_template="Stored instructions\n{chunk_text}",
    )
    items[1].location = replace(
        items[1].location, source_path="phases_v2/solitude-other"
    )
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


@pytest.mark.parametrize("mode", ["semantic", "keyword"])
def test_model_filter_combines_with_prompt_filter(mode):
    client = _client()
    params = [("q", "isolation"), ("model", "openrouter/claude-sonnet-4.6")]
    response = client.get(f"{PREFIX}/{mode}", params=params)
    assert response.status_code == 200
    assert [h["item_id"] for h in response.json()["hits"]] == ["item-causes"]
    assert response.json()["hits"][0]["model_id"] == "openrouter/claude-sonnet-4.6"
    assert (
        client.get(
            f"{PREFIX}/{mode}", params=params + [("prompt", "solitude_effects")]
        ).json()["count"]
        == 0
    )
    both = client.get(
        f"{PREFIX}/{mode}", params=params + [("model", "openai/gpt-5-mini")]
    )
    assert both.status_code == 200
    assert both.json()["count"] >= 1
    assert (
        client.get(
            f"{PREFIX}/{mode}", params={"q": "isolation", "model": "unknown"}
        ).json()["count"]
        == 0
    )


def test_model_facets_only_include_models_present_in_results():
    response = _client().get(f"{PREFIX}/models")
    assert response.status_code == 200
    assert response.json()["models"] == [
        "openai/gpt-5-mini",
        "openrouter/claude-sonnet-4.6",
    ]


@pytest.mark.parametrize("mode", ["semantic", "keyword"])
def test_source_paths_and_prompt_text_in_search_results(mode):
    client = _client()
    params = [
        ("q", "solitude"),
        ("path", "phases_v2/solitude"),
        ("model", "openai/gpt-5-mini"),
        ("prompt", "solitude_effects"),
    ]
    result = client.get(f"{PREFIX}/{mode}", params=params)
    assert result.status_code == 200
    assert [hit["item_id"] for hit in result.json()["hits"]] == ["item-effects"]
    hit = result.json()["hits"][0]
    assert hit["source_path"] == "phases_v2/solitude/paid"
    assert hit["prompt_template"] == "Stored instructions\n{chunk_text}"
    assert (
        client.get(
            f"{PREFIX}/{mode}", params={"q": "solitude", "path": "unknown"}
        ).json()["count"]
        == 0
    )


def test_path_options_include_parent_folders():
    response = _client().get(f"{PREFIX}/paths")
    assert response.status_code == 200
    assert response.json()["paths"] == [
        "phases_v2",
        "phases_v2/solitude",
        "phases_v2/solitude-other",
        "phases_v2/solitude/paid",
    ]
