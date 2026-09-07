"""Discovering papers under storage locations and recording them.

Identity is the paper's content, so the same file found at two paths is one
paper. Re-running is free: anything already recorded with rendered text is not
read, re-rendered, or re-recorded.
"""

from phases_v2 import identity
from phases_v2.papers.domain import ingest
from phases_v2.papers.fakes import (
    FakeObjectSource,
    FakePaperStore,
    FakeTextRenderer,
)


def _ingest(source, store, renderer=None, locations=("papers",), **kwargs):
    return ingest(
        list(locations),
        source=source,
        renderer=renderer or FakeTextRenderer(),
        papers=store,
        **kwargs,
    )


# -- discovery ----------------------------------------------------------


def test_papers_are_discovered_at_every_depth():
    source = FakeObjectSource()
    source.add("papers", "root.pdf", b"a")
    source.add("papers", "2024/spring.pdf", b"b")
    source.add("papers", "2024/q1/january.pdf", b"c")
    store = FakePaperStore()

    report = _ingest(source, store)

    assert report.discovered == 3
    assert {record.storage_key for record in store.papers.values()} == {
        "root.pdf",
        "2024/spring.pdf",
        "2024/q1/january.pdf",
    }


def test_several_locations_are_ingested_in_one_run():
    source = FakeObjectSource()
    source.add("papers", "a.pdf", b"a")
    source.add("archive", "b.pdf", b"b")
    store = FakePaperStore()

    report = _ingest(source, store, locations=("papers", "archive"))

    assert report.discovered == 2
    assert {record.storage_prefix for record in store.papers.values()} == {
        "papers",
        "archive",
    }


def test_a_missing_location_is_reported_and_the_rest_still_run():
    source = FakeObjectSource()
    source.add("papers", "a.pdf", b"a")
    store = FakePaperStore()

    report = _ingest(source, store, locations=("nope", "papers"))

    assert "nope" in report.failed_locations
    assert report.ingested == 1


# -- identity -----------------------------------------------------------


def test_identity_is_the_content_not_the_path():
    source = FakeObjectSource()
    source.add("papers", "one.pdf", b"identical")
    source.add("papers", "nested/two.pdf", b"identical")
    store = FakePaperStore()

    report = _ingest(source, store)

    assert report.discovered == 2
    assert len(store.papers) == 1
    assert identity.paper_id(b"identical") in store.papers


def test_the_same_content_is_only_rendered_once_in_a_run():
    source = FakeObjectSource()
    source.add("papers", "one.pdf", b"identical")
    source.add("papers", "two.pdf", b"identical")
    renderer = FakeTextRenderer()
    store = FakePaperStore()

    _ingest(source, store, renderer=renderer)

    assert len(renderer.rendered) == 1


def test_a_recorded_paper_carries_its_provenance():
    source = FakeObjectSource()
    source.add("papers", "2024/study.pdf", b"content")
    store = FakePaperStore()

    _ingest(source, store)

    [record] = store.papers.values()
    assert record.paper_id == identity.paper_id(b"content")
    assert record.content_sha256 == identity.paper_id(b"content")
    assert record.storage_prefix == "papers"
    assert record.storage_key == "2024/study.pdf"
    assert record.file_name == "study.pdf"
    assert record.size_bytes == len(b"content")
    assert record.discovered_at is not None


# -- text rendering -----------------------------------------------------


def test_rendered_text_is_stored_and_recorded_on_the_paper():
    source = FakeObjectSource()
    source.add("papers", "study.pdf", b"content")
    store = FakePaperStore()

    _ingest(source, store)

    [record] = store.papers.values()
    assert record.text_key
    assert (source.get_object("phases_v2_text", record.text_key)).decode().startswith(
        "text of study.pdf"
    )


def test_a_paper_that_cannot_be_rendered_is_reported_and_the_rest_continue():
    source = FakeObjectSource()
    source.add("papers", "broken.pdf", b"x")
    source.add("papers", "fine.pdf", b"y")
    store = FakePaperStore()

    report = _ingest(source, store, renderer=FakeTextRenderer(unreadable={"broken.pdf"}))

    assert report.ingested == 1
    assert any("broken.pdf" in key for key in report.failed_papers)
    assert len(store.papers) == 1


# -- resumability -------------------------------------------------------


def test_re_running_over_an_unchanged_location_records_nothing_new():
    source = FakeObjectSource()
    source.add("papers", "a.pdf", b"a")
    store = FakePaperStore()
    _ingest(source, store)

    report = _ingest(source, store)

    assert report.skipped == 1
    assert report.ingested == 0
    assert len(store.papers) == 1


def test_re_running_does_not_render_again():
    source = FakeObjectSource()
    source.add("papers", "a.pdf", b"a")
    store = FakePaperStore()
    renderer = FakeTextRenderer()
    _ingest(source, store, renderer=renderer)

    _ingest(source, store, renderer=renderer)

    assert len(renderer.rendered) == 1


def test_a_run_interrupted_before_rendering_is_completed_by_the_next():
    source = FakeObjectSource()
    source.add("papers", "a.pdf", b"a")
    source.add("papers", "b.pdf", b"b")
    store = FakePaperStore()
    # First run: one paper is unreadable, so it is left outstanding.
    _ingest(source, store, renderer=FakeTextRenderer(unreadable={"b.pdf"}))
    assert len(store.papers) == 1

    report = _ingest(source, store, renderer=FakeTextRenderer())

    assert report.ingested == 1
    assert report.skipped == 1
    assert len(store.papers) == 2


def test_new_papers_are_picked_up_without_touching_the_old_ones():
    source = FakeObjectSource()
    source.add("papers", "a.pdf", b"a")
    store = FakePaperStore()
    _ingest(source, store)
    renderer = FakeTextRenderer()

    source.add("papers", "b.pdf", b"b")
    report = _ingest(source, store, renderer=renderer)

    assert report.ingested == 1
    assert renderer.rendered == ["b.pdf"]


def test_the_store_is_read_once_per_run_not_once_per_paper():
    source = FakeObjectSource()
    for index in range(5):
        source.add("papers", f"{index}.pdf", str(index).encode())
    store = FakePaperStore()

    _ingest(source, store)

    assert store.reads == 1


def test_a_run_over_nothing_is_not_an_error():
    source = FakeObjectSource()
    source.add("papers", "a.pdf", b"a")
    store = FakePaperStore()

    report = _ingest(source, store, locations=())

    assert report.discovered == 0
    assert report.failed == 0
