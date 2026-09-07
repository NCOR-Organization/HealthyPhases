"""The module's only doorway to the dataset service.

Everything the pipeline writes goes through :func:`write_rows`, which always
upserts. That is not a stylistic preference: ``DatasetSpec.primary_key`` is
advisory — the store matches upserts against it but enforces no uniqueness — so
an ``append`` into a keyed dataset duplicates rows silently, with no error to
notice. Keeping one function in one file makes that invariant reviewable, and
``store_test`` fails if any other module file writes directly.
"""

from __future__ import annotations

from typing import Any

from naas_abi_core.services.dataset.DatasetPort import (
    DatasetAlreadyExistsError,
    DatasetSpec,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2.datasets.schemas import DATASETS, NAMESPACE

_BY_NAME: dict[str, DatasetSpec] = {spec.name: spec for spec in DATASETS}


def ensure_datasets(dataset: DatasetService) -> set[str]:
    """Create any declared dataset that does not exist yet.

    Runs on every engine start, in every process, so it must be cheap and
    repeatable. Returns the names it created, which is empty on all but the
    first run. Datasets that already exist are left exactly as they are —
    their rows are never touched.
    """
    existing = {info.name for info in dataset.list(namespace=NAMESPACE)}
    created = set()
    for spec in DATASETS:
        if spec.name in existing:
            continue
        try:
            dataset.create(spec)
        except DatasetAlreadyExistsError:
            # Another process created it between the list and the create.
            continue
        created.add(spec.name)
    return created


def write_rows(
    dataset: DatasetService,
    name: str,
    rows: list[dict[str, Any]],
) -> None:
    """Upsert ``rows`` into the named dataset, keyed on its primary key.

    Columns the caller omits are written as NULL, so a caller only states the
    fields it actually knows. Columns that are not in the schema are rejected
    by the store rather than silently dropped.
    """
    spec = _BY_NAME.get(name)
    if spec is None:
        raise KeyError(
            f"{name!r} is not a phases_v2 dataset; "
            f"declared datasets are {', '.join(sorted(_BY_NAME))}"
        )
    if not rows:
        return

    columns = [column.name for column in spec.columns]
    complete = [{column: row.get(column) for column in columns} for row in rows]
    unknown = sorted({key for row in rows for key in row} - set(columns))
    if unknown:
        raise KeyError(f"{name} has no column(s) {', '.join(unknown)}")

    dataset.write(name, complete, namespace=NAMESPACE, mode="upsert")


def truncate(dataset: DatasetService, name: str) -> None:
    """Empty a dataset without dropping it.

    Only for rebuilding a projection from scratch — clearing the ledger so the
    projectors re-derive the graph or the collections. Nothing in the pipeline
    calls this during normal operation.
    """
    if name not in _BY_NAME:
        raise KeyError(f"{name!r} is not a phases_v2 dataset")
    dataset.write(name, [], namespace=NAMESPACE, mode="replace")
