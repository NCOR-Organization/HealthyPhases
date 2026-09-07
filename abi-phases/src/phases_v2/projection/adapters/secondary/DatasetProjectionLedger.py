"""The ``projections`` dataset, as the projectors' ledger.

Deliberately written through an unpinned store: the reader may be pinned to a
past snapshot, but the ledger records what has been done *now*.
"""

from __future__ import annotations

from datetime import UTC, datetime

from phases_v2.ports import RowStore
from phases_v2.sql import literal


class DatasetProjectionLedger:
    def __init__(self, rows: RowStore):
        self._rows = rows

    def projected_keys(self, target: str) -> set[str]:
        return {
            row["key"]
            for row in self._rows.query(
                f"SELECT key FROM projections WHERE target = {literal(target)}"  # nosec B608
            )
        }

    def record(self, target: str, keys: list[str]) -> None:
        now = datetime.now(UTC)
        self._rows.write_rows(
            "projections",
            [{"target": target, "key": key, "projected_at": now} for key in keys],
        )
