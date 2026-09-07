"""The chunking mechanisms this module declares.

``WINDOW_512_128`` reproduces what ``phases`` does today
(``phases.utils.split_to_overlapping_chunks``): whitespace-delimited windows of
512 tokens overlapping by 128. Keeping the boundaries identical means the two
modules' chunks are comparable even though they never share a dataset.
"""

from __future__ import annotations

from phases_v2.chunking.registry import Chunker

WINDOW_512_128 = Chunker(
    name="window",
    version="1",
    params={"size": 512, "overlap": 128, "unit": "whitespace_token"},
)

DECLARED_CHUNKERS: tuple[Chunker, ...] = (WINDOW_512_128,)
