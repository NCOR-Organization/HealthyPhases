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

from naas_abi_core import logger
from naas_abi_core.services.dataset.DatasetPort import (
    DatasetAlreadyExistsError,
    DatasetNotFoundError,
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
    live = {info.name: info for info in dataset.list(namespace=NAMESPACE)}
    existing = set(live)
    _warn_about_drift(live)
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


def schema_drift(dataset: DatasetService) -> dict[str, dict[str, list[str]]]:
    """Datasets whose live columns no longer match what this module declares.

    ``ensure_datasets`` only creates what is missing — it never alters a table
    that already exists — so a schema change here leaves the warehouse behind.
    That surfaces much later as a write failing with "has no column", which is
    a long way from the cause.
    """
    live = {info.name: info for info in dataset.list(namespace=NAMESPACE)}
    return _drift(live)


def _drift(live: dict) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for spec in DATASETS:
        info = live.get(spec.name)
        if info is None:
            continue
        declared = {column.name for column in spec.columns}
        actual = {column.name for column in info.columns}
        if declared == actual:
            continue
        out[spec.name] = {
            "missing": sorted(declared - actual),
            "stale": sorted(actual - declared),
        }
    return out


def _warn_about_drift(live: dict) -> None:
    for name, diff in _drift(live).items():
        logger.warning(
            f"phases_v2: dataset {name!r} does not match its declared schema "
            f"(missing {diff['missing']}, stale {diff['stale']}). Writes to it "
            "will fail until it is recreated — see store.recreate()."
        )


def recreate(dataset: DatasetService, name: str) -> None:
    """Drop and re-create a dataset from its declared schema.

    Destructive: every row is lost. Only for a dataset whose schema has drifted
    and whose contents are rebuildable — the projections ledger, or anything
    empty. Never call it on `papers` or `extractions` holding real work.
    """
    spec = _BY_NAME.get(name)
    if spec is None:
        raise KeyError(f"{name!r} is not a phases_v2 dataset")
    try:
        dataset.drop(name, namespace=NAMESPACE)
    except DatasetNotFoundError:
        pass
    dataset.create(spec)
