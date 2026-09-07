"""The chunker registry.

A chunker's identity is its name, version and parameters, so changing any of
them yields a new ``chunker_id`` and therefore a new set of ``chunk_id``s.
That is deliberate: chunks cut with different settings are not interchangeable,
so they must not share an identity — but it does mean every extraction over
that corpus becomes outstanding work again.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from phases_v2 import identity
from phases_v2.ports import RowStore


@dataclass(frozen=True)
class Chunker:
    name: str
    version: str
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def chunker_id(self) -> str:
        return identity.chunker_id(self.name, self.version, self.params)


def register_chunkers(store: RowStore, chunkers: list[Chunker]) -> list[str]:
    """Publish every declared chunker. Returns their ids, in declaration order."""
    ids = [chunker.chunker_id for chunker in chunkers]
    repeated = [value for value, count in Counter(ids).items() if count > 1]
    if repeated:
        raise ValueError(
            "the same chunker was declared twice: " + ", ".join(sorted(repeated))
        )
    if not chunkers:
        return []

    now = datetime.now(UTC)
    store.write_rows(
        "chunkers",
        [
            {
                "chunker_id": chunker.chunker_id,
                "name": chunker.name,
                "version": chunker.version,
                "params": chunker.params,
                "registered_at": now,
            }
            for chunker in chunkers
        ],
    )
    return ids
