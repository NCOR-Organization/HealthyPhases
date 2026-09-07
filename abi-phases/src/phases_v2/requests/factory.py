"""Wiring for run requests."""

from __future__ import annotations

from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.requests.adapters.secondary.DatasetRequestStore import (
    DatasetRequestStore,
)


def request_store(engine) -> DatasetRequestStore:
    return DatasetRequestStore(DatasetRowStore(engine.services.dataset))
