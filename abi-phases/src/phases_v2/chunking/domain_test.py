"""Splitting papers into chunks, once per mechanism.

Chunks reference both their paper and the chunker that cut them, so two
mechanisms can run over the same corpus without either replacing the other.
"""

from phases_v2 import identity
from phases_v2.chunking.chunkers import WINDOW_512_128
from phases_v2.chunking.domain import chunk_papers
from phases_v2.chunking.fakes import FakeChunkStore, FakeTextSource
from phases_v2.chunking.interfaces import PaperText


class _EveryWord:
    """One chunk per word — small and exactly predictable."""

    def split(self, text: str) -> list[tuple[str, int, int]]:
        out, cursor = [], 0
        for word in text.split():
            start = text.index(word, cursor)
            out.append((word, start, start + len(word)))
            cursor = start + len(word)
        return out


def _setup(text="alpha beta gamma", paper_id="p1"):
    texts = FakeTextSource({f"{paper_id}.md": text})
    store = FakeChunkStore([PaperText(paper_id=paper_id, text_key=f"{paper_id}.md")])
    return texts, store


def _run(store, texts, chunker_id="chunker-a", mechanism=None, **kwargs):
    return chunk_papers(
        chunker_id=chunker_id,
        mechanism=mechanism or _EveryWord(),
        texts=texts,
        chunks=store,
        **kwargs,
    )


def test_a_paper_is_split_and_every_chunk_references_it():
    texts, store = _setup()

    report = _run(store, texts)

    assert report.papers_chunked == 1
    assert report.chunks_written == 3
    for chunk in store.chunks.values():
        assert chunk.paper_id == "p1"
        assert chunk.chunker_id == "chunker-a"


def test_chunks_carry_their_position_and_offsets():
    texts, store = _setup()

    _run(store, texts)

    ordered = sorted(store.chunks.values(), key=lambda c: c.seq)
    assert [c.seq for c in ordered] == [0, 1, 2]
    assert [c.text for c in ordered] == ["alpha", "beta", "gamma"]
    assert ordered[0].char_start == 0
    assert ordered[0].char_end == 5
    assert ordered[1].char_start == 6


def test_chunk_ids_are_derived_from_paper_chunker_and_position():
    texts, store = _setup()

    _run(store, texts)

    assert identity.chunk_id("p1", "chunker-a", 0) in store.chunks


def test_two_mechanisms_coexist_over_one_paper():
    texts, store = _setup()

    _run(store, texts, chunker_id="chunker-a")
    _run(store, texts, chunker_id="chunker-b")

    by_chunker = {chunk.chunker_id for chunk in store.chunks.values()}
    assert by_chunker == {"chunker-a", "chunker-b"}
    assert len(store.chunks) == 6


def test_re_running_the_same_chunker_changes_nothing():
    texts, store = _setup()
    _run(store, texts)
    before = dict(store.chunks)

    report = _run(store, texts)

    assert report.papers_chunked == 0
    assert store.chunks == before


def test_re_running_does_not_re_read_the_text():
    texts, store = _setup()
    _run(store, texts)

    _run(store, texts)

    assert texts.reads == ["p1.md"]


def test_a_run_can_be_scoped_to_a_subset_of_papers():
    texts = FakeTextSource({"p1.md": "one", "p2.md": "two"})
    store = FakeChunkStore(
        [PaperText("p1", "p1.md"), PaperText("p2", "p2.md")]
    )

    _run(store, texts, paper_ids=["p1"])

    assert {chunk.paper_id for chunk in store.chunks.values()} == {"p1"}


def test_a_paper_that_produces_no_chunks_is_counted_but_writes_nothing():
    texts = FakeTextSource({"p1.md": "   "})
    store = FakeChunkStore([PaperText("p1", "p1.md")])

    report = _run(store, texts)

    assert report.chunks_written == 0
    assert store.chunks == {}


def test_nothing_outstanding_reads_no_text_at_all():
    texts = FakeTextSource()
    store = FakeChunkStore([])

    report = _run(store, texts)

    assert report.papers_considered == 0
    assert texts.reads == []


def test_the_store_is_asked_once_which_papers_are_outstanding():
    texts, store = _setup()

    _run(store, texts)

    assert store.reads == 1
