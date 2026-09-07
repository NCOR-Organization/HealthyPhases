"""The window chunker, pinned against v1's own implementation."""

import pytest

from phases.utils import split_to_overlapping_chunks
from phases_v2.chunking.adapters.secondary.WindowChunker import WindowChunker

CORPUS = " ".join(f"word{i}" for i in range(1500))


@pytest.mark.parametrize(
    "size,overlap",
    [(512, 128), (10, 3), (4, 0), (1000, 999), (2000, 100)],
)
def test_boundaries_match_v1_exactly(size, overlap):
    # v1 is the reference: if these ever diverge, the two modules' chunks stop
    # being comparable and no test elsewhere would notice.
    mine = [text for text, _s, _e in WindowChunker(size, overlap).split(CORPUS)]

    assert mine == split_to_overlapping_chunks(CORPUS, size, overlap)


def test_the_default_is_the_v1_default():
    mine = [text for text, _s, _e in WindowChunker().split(CORPUS)]

    assert mine == split_to_overlapping_chunks(CORPUS)


def test_offsets_locate_each_chunk_in_the_source():
    text = "alpha beta gamma delta"

    chunks = WindowChunker(size=2, overlap=0).split(text)

    for chunk_text, start, end in chunks:
        assert text[start:end] == chunk_text


def test_offsets_survive_irregular_whitespace():
    text = "alpha   beta\n\ngamma"

    chunks = WindowChunker(size=1, overlap=0).split(text)

    for chunk_text, start, end in chunks:
        assert text[start:end] == chunk_text


def test_empty_and_blank_text_produce_no_chunks():
    assert WindowChunker().split("") == []
    assert WindowChunker().split("   \n  ") == []


def test_text_shorter_than_the_window_is_one_chunk():
    assert len(WindowChunker(size=512, overlap=128).split("just a few words")) == 1


def test_nonsensical_settings_are_rejected():
    with pytest.raises(ValueError):
        WindowChunker(size=0)
    with pytest.raises(ValueError):
        WindowChunker(size=10, overlap=10)
    with pytest.raises(ValueError):
        WindowChunker(size=10, overlap=-1)
