from __future__ import annotations

from phases.app.models import ItemLocation, SearchHit


def test_paper_name_basename_from_path():
    loc = ItemLocation(paper_path="/abs/papers/solitude/pmc/PMC123.pdf")
    assert loc.paper_name == "PMC123.pdf"


def test_paper_name_none_when_no_path():
    assert ItemLocation().paper_name is None


def test_search_hit_build_flattens_location():
    loc = ItemLocation(
        pipeline="causes",
        model="gpt-5-mini",
        chunk_id="c1",
        chunk_number=4,
        chunk_text="ctx",
        paper_path="/p/x.pdf",
    )
    hit = SearchHit.build(
        extracted_item_id="id1",
        extracted_text="claim",
        location=loc,
        score=0.42,
    )
    assert hit.pipeline == "causes"
    assert hit.chunk_number == 4
    assert hit.paper_name == "x.pdf"
    assert hit.score == 0.42


def test_search_hit_build_tolerates_missing_location():
    hit = SearchHit.build(
        extracted_item_id="id1", extracted_text="claim", location=None
    )
    assert hit.paper_path is None
    assert hit.paper_name is None
    assert hit.score is None
