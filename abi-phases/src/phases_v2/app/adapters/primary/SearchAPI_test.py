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


def _large_client(size=523):
    from phases_v2.search.fakes import FakeItem
    from phases_v2.search.models import ItemLocation

    items = [
        FakeItem(
            f"item-{i:04d}",
            f'=claim "quoted", line\n{i}',
            ItemLocation(
                prompt_name="claims",
                model_id="m",
                source_path="root/a",
                paper_name="a.pdf",
                chunk_seq=0,
                paper_id="a",
                prompt_template="instructions\n{chunk_text}",
            ),
            similarity=0.9 if i < 200 else 0.5,
        )
        for i in range(size)
    ]
    service = SearchService(FakeSemanticIndex(items), FakeExtractedItems(items))
    app = FastAPI()
    register(app, service)
    return TestClient(app), service


@pytest.mark.parametrize("mode", ["keyword", "semantic"])
def test_pages_expose_total_and_reach_every_match_without_duplicates(mode):
    client, _ = _large_client()
    offset, ids = 0, []
    while True:
        response = client.get(
            f"{PREFIX}/{mode}",
            params={
                "q": "claim",
                "k" if mode == "semantic" else "limit": 100,
                "offset": offset,
                "prompt": "claims",
                "model": "m",
                "path": "root",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == data["total"] == 523
        assert data["page_count"] == len(data["hits"]) <= 100
        ids.extend(hit["item_id"] for hit in data["hits"])
        if not data["has_more"]:
            assert data["next_offset"] is None
            break
        offset = data["next_offset"]
    assert len(ids) == len(set(ids)) == 523
    assert ids == sorted(ids)
    beyond = client.get(f"{PREFIX}/{mode}", params={"q": "claim", "offset": 999}).json()
    assert beyond["hits"] == [] and beyond["total"] == 523


@pytest.mark.parametrize("mode", ["keyword", "semantic"])
def test_export_reads_all_matches_independently_of_visible_page_and_escapes_cells(mode):
    import csv
    import io

    client, _ = _large_client()
    visible = client.get(
        f"{PREFIX}/{mode}", params={"q": "claim", "k": 10, "limit": 10}
    )
    assert len(visible.json()["hits"]) == 10
    response = client.get(
        f"{PREFIX}/export",
        params={
            "q": "claim",
            "mode": mode,
            "prompt": "claims",
            "model": "m",
            "path": "root/a",
        },
    )
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == 523
    assert len({row["item_id"] for row in rows}) == 523
    assert rows[0]["extracted_text"] == '\'=claim "quoted", line\n0'
    assert rows[0]["prompt_template"] == "instructions\n{chunk_text}"
    assert all(row["query"] == "claim" and row["mode"] == mode for row in rows)
    no_matches = client.get(
        f"{PREFIX}/export", params={"q": "claim", "mode": mode, "model": "missing"}
    )
    assert (
        list(csv.DictReader(io.StringIO(no_matches.content.decode("utf-8-sig")))) == []
    )


def test_semantic_total_and_export_respect_score_threshold_and_late_prompt_matches():
    import csv
    import io

    client, service = _large_client()
    for item in service._items.items[:200]:
        item.location = replace(item.location, prompt_name="other")
    response = client.get(
        f"{PREFIX}/semantic", params={"q": "claim", "prompt": "claims", "k": 10}
    )
    assert response.json()["total"] == 323
    assert response.json()["hits"][0]["item_id"] == "item-0200"
    high = client.get(
        f"{PREFIX}/semantic", params={"q": "claim", "score_threshold": 0.8}
    )
    assert high.json()["total"] == 200
    export = client.get(
        f"{PREFIX}/export",
        params={"q": "claim", "mode": "semantic", "score_threshold": 0.8},
    )
    assert (
        len(list(csv.DictReader(io.StringIO(export.content.decode("utf-8-sig")))))
        == 200
    )


@pytest.mark.parametrize(
    "params",
    [
        {"offset": -1},
        {"limit": 101},
        {"limit": 0},
        {"score_threshold": 2},
        {"snapshot": -1},
    ],
)
def test_search_contract_rejects_invalid_pagination(params):
    response = _client().get(f"{PREFIX}/keyword", params={"q": "claim", **params})
    assert response.status_code == 422


def test_failed_search_or_export_returns_error_not_false_zero_or_partial_csv():
    client, service = _large_client()

    def broken(*args, **kwargs):
        raise RuntimeError("database unavailable")

    service._items.keyword_count = broken
    assert client.get(f"{PREFIX}/keyword", params={"q": "claim"}).status_code == 503
    original = service._items.keyword_search

    def fail_second_batch(*args, **kwargs):
        if args[-1] >= 500:
            raise RuntimeError("second batch failed")
        return original(*args, **kwargs)

    service._items.keyword_search = fail_second_batch
    response = client.get(f"{PREFIX}/export", params={"q": "claim", "mode": "keyword"})
    assert response.status_code == 503
    assert "text/csv" not in response.headers["content-type"]
