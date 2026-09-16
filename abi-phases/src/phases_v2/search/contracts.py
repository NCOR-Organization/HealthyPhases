"""Reusable port-contract checks.

Any concrete :class:`ISemanticIndexPort` / :class:`IExtractedItemsPort`
implementation can be validated against these, given a store seeded with the
canonical fixture below. Real adapter tests seed their backing store with
:func:`canonical_items` and then call the ``assert_*`` helpers.
"""

from __future__ import annotations

from phases_v2.search.interfaces import IExtractedItemsPort, ISemanticIndexPort
from phases_v2.search.models import ItemLocation

CANONICAL_QUERY = "solitude and stress"


def canonical_items():
    """The fixture every adapter contract test should seed.

    Imported lazily by callers; returns ``FakeItem``-shaped records that real
    adapters translate into their own storage rows.
    """
    from phases_v2.search.fakes import FakeItem

    return [
        FakeItem(
            "item-effects",
            "Solitude reduces stress.",
            ItemLocation(
                prompt_id="prompt-effects-hash",
                prompt_name="solitude_effects",
                model_id="openai/gpt-5-mini",
                chunk_id="chunk-1",
                chunk_seq=1,
                chunk_text="In several studies solitude reduces stress.",
                paper_id="paper-a",
                paper_name="a.pdf",
            ),
            similarity=0.91,
        ),
        FakeItem(
            "item-causes",
            "Isolation increases loneliness.",
            ItemLocation(
                prompt_id="prompt-causes-hash",
                prompt_name="solitude_causes",
                model_id="openai/gpt-5-mini",
                chunk_id="chunk-2",
                chunk_seq=2,
                chunk_text="Prolonged isolation increases loneliness over time.",
                paper_id="paper-b",
                paper_name="b.pdf",
            ),
            similarity=0.55,
        ),
    ]


def assert_semantic_index_contract(index: ISemanticIndexPort) -> None:
    results = index.search(CANONICAL_QUERY, k=10)
    assert results, "semantic search returned no results for the canonical query"

    ids = [r.item_id for r in results]
    assert "item-effects" in ids
    for r in results:
        assert r.item_id, "every match must carry an item_id"
        assert isinstance(r.score, float)

    # k is an upper bound.
    assert len(index.search(CANONICAL_QUERY, k=1)) <= 1

    # Threshold filters low-similarity hits.
    high = index.search(CANONICAL_QUERY, k=10, score_threshold=0.9)
    assert all(r.score >= 0.9 for r in high)


def assert_extracted_items_contract(items: IExtractedItemsPort) -> None:
    # resolve_locations
    locs = items.resolve_locations(["item-effects", "item-causes", "missing"])
    assert "missing" not in locs
    effects = locs["item-effects"]
    assert effects.prompt_name == "solitude_effects"
    assert effects.chunk_seq == 1
    assert effects.paper_name == "a.pdf"
    assert effects.chunk_text

    # keyword_search: all tokens required (case-insensitive)
    hits = items.keyword_search(["solitude", "stress"], prompts=None, limit=10)
    assert [h[0] for h in hits] == ["item-effects"]

    none = items.keyword_search(["loneliness", "stress"], prompts=None, limit=10)
    assert none == []

    # keyword_search: prompt facet
    only_causes = items.keyword_search(["isolation"], prompts=["solitude_causes"], limit=10)
    assert [h[0] for h in only_causes] == ["item-causes"]
    assert items.keyword_search(["isolation"], prompts=["solitude_effects"], limit=10) == []

    # list_prompts
    assert set(items.list_prompts()) >= {"solitude_causes", "solitude_effects"}
