from __future__ import annotations

from phases.app.domain import SearchService, tokenize
from phases.app.fakes import FakeItem, FakeKnowledgeGraph, FakeSemanticIndex
from phases.app.models import ItemLocation


def _loc(pipeline: str, number: int = 0, path: str = "/p/a.pdf") -> ItemLocation:
    return ItemLocation(
        pipeline=pipeline,
        model="gpt-5-mini",
        chunk_id=f"c{number}",
        chunk_number=number,
        chunk_text=f"context for {pipeline} {number}",
        paper_path=path,
    )


def _items() -> list[FakeItem]:
    return [
        FakeItem("a", "Solitude reduces stress.", _loc("effects", 1), similarity=0.9),
        FakeItem("b", "Loneliness raises cortisol.", _loc("causes", 2), similarity=0.7),
        FakeItem("c", "Older adults seek solitude.", _loc("when", 3), similarity=0.5),
    ]


def test_tokenize_dedups_and_lowercases():
    assert tokenize("Solitude SOLITUDE stress!") == ["solitude", "stress"]
    assert tokenize("   ") == []


def test_semantic_search_enriches_and_orders_by_score():
    items = _items()
    svc = SearchService(FakeSemanticIndex(items), FakeKnowledgeGraph(items))

    hits = svc.semantic_search("stress", k=2)

    assert [h.extracted_item_id for h in hits] == ["a", "b"]
    top = hits[0]
    assert top.score == 0.9
    assert top.pipeline == "effects"
    assert top.paper_name == "a.pdf"
    assert top.chunk_number == 1
    assert top.chunk_text.startswith("context for effects")


def test_semantic_search_respects_pipeline_facet():
    items = _items()
    svc = SearchService(FakeSemanticIndex(items), FakeKnowledgeGraph(items))

    hits = svc.semantic_search("stress", k=10, pipelines=["causes"])

    assert [h.extracted_item_id for h in hits] == ["b"]


def test_semantic_search_score_threshold():
    items = _items()
    svc = SearchService(FakeSemanticIndex(items), FakeKnowledgeGraph(items))

    hits = svc.semantic_search("stress", k=10, score_threshold=0.75)

    assert [h.extracted_item_id for h in hits] == ["a"]


def test_semantic_search_empty_query_returns_nothing():
    svc = SearchService(FakeSemanticIndex(_items()), FakeKnowledgeGraph(_items()))
    assert svc.semantic_search("   ") == []


def test_keyword_search_requires_all_tokens():
    items = _items()
    svc = SearchService(FakeSemanticIndex(items), FakeKnowledgeGraph(items))

    assert [h.extracted_item_id for h in svc.keyword_search("solitude")] == ["a", "c"]
    assert [h.extracted_item_id for h in svc.keyword_search("solitude stress")] == ["a"]
    assert svc.keyword_search("nonexistentword") == []


def test_keyword_search_pipeline_filter_and_no_score():
    items = _items()
    svc = SearchService(FakeSemanticIndex(items), FakeKnowledgeGraph(items))

    hits = svc.keyword_search("solitude", pipelines=["when"])
    assert [h.extracted_item_id for h in hits] == ["c"]
    assert hits[0].score is None
    assert hits[0].paper_name == "a.pdf"


def test_list_pipelines_sorted_distinct():
    items = _items()
    svc = SearchService(FakeSemanticIndex(items), FakeKnowledgeGraph(items))
    assert svc.list_pipelines() == ["causes", "effects", "when"]
