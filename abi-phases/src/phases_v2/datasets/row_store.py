"""The dataset-backed :class:`~phases_v2.ports.RowStore`.

Thin by design: every write goes through ``store.write_rows`` so the
upsert-only invariant holds for the domains too, and reads carry the pinned
snapshot when there is one.
"""

from __future__ import annotations

from typing import Any

from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2.datasets import store
from phases_v2.datasets.schemas import NAMESPACE


class DatasetRowStore:
    def __init__(self, dataset: DatasetService, snapshot: int | None = None):
        self._dataset = dataset
        self._snapshot = snapshot

    def write_rows(self, name: str, rows: list[dict[str, Any]]) -> None:
        if self._snapshot is not None:
            raise RuntimeError(
                "this store is pinned to a snapshot for reading and must not "
                "be written through"
            )
        store.write_rows(self._dataset, name, rows)

    def query(self, sql: str) -> list[dict[str, Any]]:
        return self._dataset.query(
            sql, namespace=NAMESPACE, snapshot_id=self._snapshot
        ).rows

    def snapshot(self) -> int | None:
        # Snapshots are catalog-wide, so describing any dataset reports the
        # version of the whole store.
        return self._dataset.describe("papers", namespace=NAMESPACE).snapshot_id

    def at_snapshot(self, snapshot: int | None) -> DatasetRowStore:
        return DatasetRowStore(self._dataset, snapshot)
