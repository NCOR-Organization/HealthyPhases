"""Overlapping whitespace-token windows.

Reproduces ``phases.utils.split_to_overlapping_chunks`` exactly, so the two
modules cut the same text at the same places and their extractions stay
comparable — the boundary logic is pinned by a test that runs v1's own
function.

The one thing added here is offsets: v1 returns text only, but a chunk needs
to be locatable in the paper it came from.
"""

from __future__ import annotations


class WindowChunker:
    def __init__(self, size: int = 512, overlap: int = 128):
        if size <= 0:
            raise ValueError("size must be positive")
        if not 0 <= overlap < size:
            raise ValueError("overlap must be non-negative and smaller than size")
        self._size = size
        self._overlap = overlap

    def split(self, text: str) -> list[tuple[str, int, int]]:
        tokens = self._tokens(text)
        if not tokens:
            return []

        chunks: list[tuple[str, int, int]] = []
        start = 0
        while start < len(tokens):
            end = start + self._size
            window = tokens[start:end]
            chunks.append(
                (
                    " ".join(word for word, _s, _e in window),
                    window[0][1],
                    window[-1][2],
                )
            )
            if end >= len(tokens):
                break
            start += self._size - self._overlap
        return chunks

    @staticmethod
    def _tokens(text: str) -> list[tuple[str, int, int]]:
        """Whitespace-delimited words with their offsets in ``text``."""
        tokens: list[tuple[str, int, int]] = []
        cursor = 0
        for word in text.split():
            start = text.index(word, cursor)
            tokens.append((word, start, start + len(word)))
            cursor = start + len(word)
        return tokens
