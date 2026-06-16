"""Reusable port-contract checks.

Any concrete :class:`ISemanticIndexPort` / :class:`IKnowledgeGraphPort`
implementation can be validated against these, given a store seeded with the
canonical fixture below. Real adapter tests (Qdrant / SPARQL) seed their backing
store with :func:`canonical_items` and then call the ``assert_*`` helpers.
"""

from __future__ import annotations

from phases.app.interfaces import IKnowledgeGraphPort, ISemanticIndexPort
from phases.app.models import ItemLocation

CANONICAL_QUERY = "solitude and stress"


def canonical_items():
    """The fixture every adapter contract test should seed.

    Imported lazily by callers; returns ``FakeItem``-shaped records that real
    adapters translate into their own storage rows.
    """
    from phases.app.fakes import FakeItem

    return [
        FakeItem(
            "item-effects",
            "Solitude reduces stress.",
            ItemLocation(
                pipeline="effects",
                model="gpt-5-mini",
                chunk_id="chunk-1",
                chunk_number=1,
                chunk_text="In several studies solitude reduces stress.",
                paper_path="/papers/solitude/a.pdf",
            ),
            similarity=0.91,
        ),
        FakeItem(
            "item-causes",
            "Isolation increases loneliness.",
            ItemLocation(
                pipeline="causes",
                model="gpt-5-mini",
                chunk_id="chunk-2",
                chunk_number=2,
                chunk_text="Prolonged isolation increases loneliness over time.",
                paper_path="/papers/solitude/b.pdf",
            ),
            similarity=0.55,
        ),
    ]


def assert_semantic_index_contract(index: ISemanticIndexPort) -> None:
    results = index.search(CANONICAL_QUERY, k=10)
    assert results, "semantic search returned no results for the canonical query"

    ids = [r.extracted_item_id for r in results]
    assert "item-effects" in ids
    for r in results:
        assert r.extracted_item_id, "every match must carry an extracted_item_id"
        assert isinstance(r.score, float)

    # k is an upper bound.
    assert len(index.search(CANONICAL_QUERY, k=1)) <= 1

    # Threshold filters low-similarity hits.
    high = index.search(CANONICAL_QUERY, k=10, score_threshold=0.9)
    assert all(r.score >= 0.9 for r in high)


def assert_knowledge_graph_contract(kg: IKnowledgeGraphPort) -> None:
    # resolve_locations
    locs = kg.resolve_locations(["item-effects", "item-causes", "missing"])
    assert "missing" not in locs
    effects = locs["item-effects"]
    assert effects.pipeline == "effects"
    assert effects.chunk_number == 1
    assert effects.paper_name == "a.pdf"
    assert effects.chunk_text

    # keyword_search: all tokens required (case-insensitive)
    hits = kg.keyword_search(["solitude", "stress"], pipelines=None, limit=10)
    assert [h[0] for h in hits] == ["item-effects"]

    none = kg.keyword_search(["loneliness", "stress"], pipelines=None, limit=10)
    assert none == []

    # keyword_search: pipeline facet
    only_causes = kg.keyword_search(["isolation"], pipelines=["causes"], limit=10)
    assert [h[0] for h in only_causes] == ["item-causes"]
    assert kg.keyword_search(["isolation"], pipelines=["effects"], limit=10) == []

    # list_pipelines
    assert set(kg.list_pipelines()) >= {"causes", "effects"}
