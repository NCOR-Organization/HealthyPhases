"""The module's only doorway to the dataset service.

Two invariants live here. Creation is idempotent, because every engine process
runs it on load. And every write is an upsert — ``primary_key`` is advisory, so
a single stray ``append`` would duplicate rows with no error and no warning.
"""

import ast
import pathlib

import pytest
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2.datasets import store
from phases_v2.datasets.schemas import DATASETS, NAMESPACE


@pytest.fixture
def dataset(tmp_path) -> DatasetService:
    return DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path / 'catalog.sqlite'}",
            data_path=str(tmp_path / "data") + "/",
        )
    )


# -- ensure_datasets ----------------------------------------------------


def test_ensure_datasets_creates_every_declared_dataset(dataset):
    created = store.ensure_datasets(dataset)

    assert created == {spec.name for spec in DATASETS}
    existing = {info.name for info in dataset.list(namespace=NAMESPACE)}
    assert existing == {spec.name for spec in DATASETS}


def test_ensure_datasets_is_idempotent(dataset):
    store.ensure_datasets(dataset)

    created = store.ensure_datasets(dataset)

    assert created == set()
    existing = [info.name for info in dataset.list(namespace=NAMESPACE)]
    assert len(existing) == len(set(existing)) == len(DATASETS)


def test_ensure_datasets_creates_only_what_is_missing(dataset):
    store.ensure_datasets(dataset)
    dataset.drop("chunks", namespace=NAMESPACE)

    created = store.ensure_datasets(dataset)

    assert created == {"chunks"}


def test_ensure_datasets_preserves_rows_already_written(dataset):
    store.ensure_datasets(dataset)
    store.write_rows(dataset, "papers", [_paper("p1")])

    store.ensure_datasets(dataset)

    assert _paper_ids(dataset) == ["p1"]


# -- write_rows ---------------------------------------------------------


def test_write_rows_upserts_rather_than_appending(dataset):
    store.ensure_datasets(dataset)

    store.write_rows(dataset, "papers", [_paper("p1", file_name="first.pdf")])
    store.write_rows(dataset, "papers", [_paper("p1", file_name="second.pdf")])

    rows = dataset.query(
        "SELECT paper_id, file_name FROM papers", namespace=NAMESPACE
    ).rows
    assert rows == [{"paper_id": "p1", "file_name": "second.pdf"}]


def test_write_rows_writes_several_rows_at_once(dataset):
    store.ensure_datasets(dataset)

    store.write_rows(dataset, "papers", [_paper("p1"), _paper("p2")])

    assert _paper_ids(dataset) == ["p1", "p2"]


def test_write_rows_accepts_an_empty_batch(dataset):
    store.ensure_datasets(dataset)

    store.write_rows(dataset, "papers", [])

    assert _paper_ids(dataset) == []


def test_write_rows_round_trips_a_json_column(dataset):
    store.ensure_datasets(dataset)

    store.write_rows(
        dataset,
        "chunkers",
        [
            {
                "chunker_id": "c1",
                "name": "window",
                "version": "1",
                "params": {"size": 512, "overlap": 128},
                "registered_at": None,
            }
        ],
    )

    [row] = dataset.query("SELECT params FROM chunkers", namespace=NAMESPACE).rows
    assert row["params"] == {"size": 512, "overlap": 128}


def test_write_rows_rejects_an_unknown_dataset(dataset):
    store.ensure_datasets(dataset)

    with pytest.raises(KeyError):
        store.write_rows(dataset, "not_a_dataset", [])


def test_write_rows_fills_declared_columns_the_caller_omitted(dataset):
    # The store requires every column to be present; making the caller repeat
    # a dozen Nones per row is how rows drift out of sync with the schema.
    store.ensure_datasets(dataset)

    store.write_rows(dataset, "papers", [{"paper_id": "p1"}])

    [row] = dataset.query(
        "SELECT paper_id, file_name FROM papers", namespace=NAMESPACE
    ).rows
    assert row == {"paper_id": "p1", "file_name": None}


def test_write_rows_rejects_a_column_that_is_not_in_the_schema(dataset):
    store.ensure_datasets(dataset)

    with pytest.raises(Exception):
        store.write_rows(dataset, "papers", [{"paper_id": "p1", "nope": 1}])


# -- the invariant that makes all of the above true ---------------------


def test_store_is_the_only_module_code_that_writes_to_a_dataset():
    # Parsed, not grepped: prose in a docstring that mentions mode="upsert" is
    # not a write, and a guard that cannot tell the difference is one people
    # learn to ignore.
    module_root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in sorted(module_root.rglob("*.py")):
        if path.name in {"store.py", "store_test.py"}:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            writes = (
                isinstance(node.func, ast.Attribute) and node.func.attr == "write"
            )
            passes_mode = any(kw.arg == "mode" for kw in node.keywords)
            if writes or passes_mode:
                offenders.append(
                    f"{path.relative_to(module_root)}:{node.lineno}"
                )

    assert offenders == [], (
        "these call sites write to a dataset directly instead of going through "
        f"store.write_rows, so they can bypass mode='upsert': {offenders}"
    )


# -- helpers ------------------------------------------------------------


def _paper(paper_id: str, **overrides) -> dict:
    row = {"paper_id": paper_id, "file_name": f"{paper_id}.pdf"}
    row.update(overrides)
    return row


def _paper_ids(dataset: DatasetService) -> list[str]:
    return [
        row["paper_id"]
        for row in dataset.query(
            "SELECT paper_id FROM papers ORDER BY paper_id", namespace=NAMESPACE
        ).rows
    ]


def test_truncate_empties_a_dataset_without_dropping_it(dataset):
    store.ensure_datasets(dataset)
    store.write_rows(dataset, "papers", [_paper("p1"), _paper("p2")])

    store.truncate(dataset, "papers")

    assert _paper_ids(dataset) == []
    assert "papers" in {info.name for info in dataset.list(namespace=NAMESPACE)}


def test_truncate_rejects_an_unknown_dataset(dataset):
    with pytest.raises(KeyError):
        store.truncate(dataset, "not_a_dataset")


# -- schema drift -------------------------------------------------------


def test_a_matching_warehouse_reports_no_drift(dataset):
    store.ensure_datasets(dataset)

    assert store.schema_drift(dataset) == {}


def test_a_dataset_missing_a_declared_column_is_reported(dataset):
    # ensure_datasets never alters an existing table, so a schema change here
    # leaves the warehouse behind. Without this it surfaces much later as a
    # write failing with "has no column".
    from naas_abi_core.services.dataset.DatasetPort import ColumnSpec, DatasetSpec

    dataset.create(
        DatasetSpec(
            name="papers",
            namespace=NAMESPACE,
            columns=(ColumnSpec(name="paper_id", type="string"),),
            primary_key=("paper_id",),
        )
    )

    drift = store.schema_drift(dataset)

    assert "papers" in drift
    assert "file_name" in drift["papers"]["missing"]


def test_a_dataset_with_a_stale_column_is_reported(dataset):
    from naas_abi_core.services.dataset.DatasetPort import ColumnSpec, DatasetSpec

    columns = tuple(
        ColumnSpec(name=c.name, type=c.type) for c in store._BY_NAME["papers"].columns
    ) + (ColumnSpec(name="left_over", type="string"),)
    dataset.create(
        DatasetSpec(
            name="papers", namespace=NAMESPACE, columns=columns, primary_key=("paper_id",)
        )
    )

    assert store.schema_drift(dataset)["papers"]["stale"] == ["left_over"]


def test_recreate_brings_a_drifted_dataset_back_to_its_declared_schema(dataset):
    from naas_abi_core.services.dataset.DatasetPort import ColumnSpec, DatasetSpec

    dataset.create(
        DatasetSpec(
            name="papers",
            namespace=NAMESPACE,
            columns=(ColumnSpec(name="paper_id", type="string"),),
            primary_key=("paper_id",),
        )
    )

    store.recreate(dataset, "papers")

    assert "papers" not in store.schema_drift(dataset)


def test_recreate_rejects_an_unknown_dataset(dataset):
    with pytest.raises(KeyError):
        store.recreate(dataset, "not_a_dataset")
