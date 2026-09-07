"""In-memory doubles for domain tests.

The fake store honours the one rule that matters — writes are upserts keyed on
the real schema's primary key — so a domain test cannot pass here and then
duplicate rows against the real store.
"""

from __future__ import annotations

from typing import Any

from phases_v2.datasets.schemas import DATASETS

_KEYS: dict[str, tuple[str, ...]] = {
    spec.name: spec.primary_key for spec in DATASETS
}
_COLUMNS: dict[str, tuple[str, ...]] = {
    spec.name: tuple(column.name for column in spec.columns) for spec in DATASETS
}


class InMemoryRowStore:
    """A :class:`~phases_v2.ports.RowStore` backed by dictionaries."""

    def __init__(self) -> None:
        self._tables: dict[str, dict[tuple, dict[str, Any]]] = {
            name: {} for name in _KEYS
        }
        self._version = 0
        self.writes: list[str] = []

    # -- RowStore -------------------------------------------------------

    def write_rows(self, name: str, rows: list[dict[str, Any]]) -> None:
        if name not in self._tables:
            raise KeyError(f"{name!r} is not a phases_v2 dataset")
        columns = _COLUMNS[name]
        for row in rows:
            unknown = sorted(set(row) - set(columns))
            if unknown:
                raise KeyError(f"{name} has no column(s) {', '.join(unknown)}")
        if not rows:
            return
        self.writes.append(name)
        for row in rows:
            complete = {column: row.get(column) for column in columns}
            key = tuple(complete[column] for column in _KEYS[name])
            if any(part is None for part in key):
                raise ValueError(f"{name} row has a null primary key: {key}")
            self._tables[name][key] = complete
        self._version += 1

    def query(self, sql: str) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "the fake store does not run SQL; give the domain a port method "
            "that says what it needs and implement that here"
        )

    def snapshot(self) -> int | None:
        return self._version

    def at_snapshot(self, snapshot: int | None) -> InMemoryRowStore:
        # Nothing in the fake mutates history, so reading "as of" a version is
        # only meaningful for the current one.
        return self

    # -- inspection, for tests ------------------------------------------

    def rows(self, name: str) -> list[dict[str, Any]]:
        return list(self._tables[name].values())

    def count(self, name: str) -> int:
        return len(self._tables[name])
