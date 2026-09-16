from __future__ import annotations

from phases_v2.search.models import ItemLocation, SearchHit


def test_search_hit_build_flattens_location():
    loc = ItemLocation(
        prompt_id="hash-abc",
        prompt_name="solitude_causes",
        model_id="openai/gpt-5-mini",
        chunk_id="c1",
        chunk_seq=4,
        chunk_text="ctx",
        paper_id="paper-x",
        paper_name="x.pdf",
    )

    hit = SearchHit.build(item_id="id1", extracted_text="claim", location=loc, score=0.42)

    assert hit.prompt_name == "solitude_causes"
    assert hit.chunk_seq == 4
    assert hit.paper_name == "x.pdf"
    assert hit.score == 0.42


def test_search_hit_build_tolerates_missing_location():
    hit = SearchHit.build(item_id="id1", extracted_text="claim", location=None)

    assert hit.paper_id is None
    assert hit.paper_name is None
    assert hit.score is None
