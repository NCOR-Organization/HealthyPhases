"""What the domains need from storage, stated without naming a technology.

Domains depend on these protocols, never on ``DatasetService``. The real
implementations live in ``phases_v2.datasets.row_store``; the in-memory ones
used by domain tests live in ``phases_v2.fakes``.
"""

from __future__ import annotations

from typing import Any, Protocol


class RowStore(Protocol):
    """Rows in named tables, written by key and read with SQL."""

    def write_rows(self, name: str, rows: list[dict[str, Any]]) -> None:
        """Upsert ``rows`` into ``name``, matched on that table's primary key.

        Writing the same key twice leaves one row carrying the later values.
        There is no append: a caller that wants two rows must give them two
        different keys.
        """
        ...

    def query(self, sql: str) -> list[dict[str, Any]]:
        """Run a read-only query across the pipeline's tables."""
        ...

    def snapshot(self) -> int | None:
        """The current version of the whole store, if it has one.

        A projection run pins this once and reads everything at it, so a write
        landing mid-run cannot produce a half-projected result.
        """
        ...

    def at_snapshot(self, snapshot: int | None) -> RowStore:
        """This same store, reading as of ``snapshot``."""
        ...
