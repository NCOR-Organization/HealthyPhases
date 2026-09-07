"""The declared chunkers, and the boundaries they must reproduce."""

from phases_v2.chunking.chunkers import DECLARED_CHUNKERS, WINDOW_512_128
from phases_v2.chunking.registry import Chunker


def test_the_v1_compatible_chunker_is_declared():
    assert WINDOW_512_128 in DECLARED_CHUNKERS


def test_its_id_is_stable():
    assert WINDOW_512_128.chunker_id == Chunker(
        name="window",
        version="1",
        params={"size": 512, "overlap": 128, "unit": "whitespace_token"},
    ).chunker_id


def test_its_id_is_readable_in_a_partition_value():
    # chunker_id is the partition column for `chunks`, so a human reads it.
    assert WINDOW_512_128.chunker_id.startswith("window_1_")


def test_declared_chunker_ids_are_unique():
    ids = [chunker.chunker_id for chunker in DECLARED_CHUNKERS]
    assert len(ids) == len(set(ids))


def test_it_records_the_settings_v1_uses():
    assert WINDOW_512_128.params["size"] == 512
    assert WINDOW_512_128.params["overlap"] == 128
