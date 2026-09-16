from __future__ import annotations

from phases_v2.search.domain import SearchService, tokenize
from phases_v2.search.fakes import FakeExtractedItems, FakeItem, FakeSemanticIndex
from phases_v2.search.models import ItemLocation


def _loc(prompt_name: str, seq: int = 0, paper_name: str = "a.pdf") -> ItemLocation:
    return ItemLocation(
        prompt_id=f"prompt-{prompt_name}-hash",
        prompt_name=prompt_name,
        model_id="openai/gpt-5-mini",
        chunk_id=f"c{seq}",
        chunk_seq=seq,
        chunk_text=f"context for {prompt_name} {seq}",
        paper_id="paper-a",
        paper_name=paper_name,
    )


def _items() -> list[FakeItem]:
    return [
        FakeItem("a", "Solitude reduces stress.", _loc("solitude_effects", 1), similarity=0.9),
        FakeItem("b", "Loneliness raises cortisol.", _loc("solitude_causes", 2), similarity=0.7),
        FakeItem("c", "Older adults seek solitude.", _loc("solitude_when", 3), similarity=0.5),
    ]


def test_tokenize_dedups_and_lowercases():
    assert tokenize("Solitude SOLITUDE stress!") == ["solitude", "stress"]
    assert tokenize("   ") == []


def test_semantic_search_enriches_and_orders_by_score():
    items = _items()
    svc = SearchService(FakeSemanticIndex(items), FakeExtractedItems(items))

    hits = svc.semantic_search("stress", k=2)

    assert [h.item_id for h in hits] == ["a", "b"]
    top = hits[0]
    assert top.score == 0.9
    assert top.prompt_name == "solitude_effects"
    assert top.paper_name == "a.pdf"
    assert top.chunk_seq == 1
    assert top.chunk_text.startswith("context for solitude_effects")


def test_semantic_search_respects_prompt_facet():
    items = _items()
    svc = SearchService(FakeSemanticIndex(items), FakeExtractedItems(items))

    hits = svc.semantic_search("stress", k=10, prompts=["solitude_causes"])

    assert [h.item_id for h in hits] == ["b"]


def test_semantic_search_score_threshold():
    items = _items()
    svc = SearchService(FakeSemanticIndex(items), FakeExtractedItems(items))

    hits = svc.semantic_search("stress", k=10, score_threshold=0.75)

    assert [h.item_id for h in hits] == ["a"]


def test_semantic_search_empty_query_returns_nothing():
    svc = SearchService(FakeSemanticIndex(_items()), FakeExtractedItems(_items()))
    assert svc.semantic_search("   ") == []


def test_keyword_search_requires_all_tokens():
    items = _items()
    svc = SearchService(FakeSemanticIndex(items), FakeExtractedItems(items))

    assert [h.item_id for h in svc.keyword_search("solitude")] == ["a", "c"]
    assert [h.item_id for h in svc.keyword_search("solitude stress")] == ["a"]
    assert svc.keyword_search("nonexistentword") == []


def test_keyword_search_prompt_filter_and_no_score():
    items = _items()
    svc = SearchService(FakeSemanticIndex(items), FakeExtractedItems(items))

    hits = svc.keyword_search("solitude", prompts=["solitude_when"])
    assert [h.item_id for h in hits] == ["c"]
    assert hits[0].score is None
    assert hits[0].paper_name == "a.pdf"


def test_list_prompts_sorted_distinct():
    items = _items()
    svc = SearchService(FakeSemanticIndex(items), FakeExtractedItems(items))
    assert svc.list_prompts() == ["solitude_causes", "solitude_effects", "solitude_when"]
