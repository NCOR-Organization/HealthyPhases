"""The schemas are the module's contract with the dataset service.

Two properties matter enough to pin here rather than discover at runtime:
identifiers the store will accept, and a primary key on every dataset. The
second is load-bearing — ``DatasetSpec.primary_key`` is advisory, so a dataset
that declares none silently accepts duplicate rows on upsert.
"""

import re

from naas_abi_core.services.dataset.DatasetPort import IDENTIFIER_PATTERN

from phases_v2.datasets.schemas import DATASETS, NAMESPACE

_IDENTIFIER = re.compile(IDENTIFIER_PATTERN)


def test_the_namespace_is_a_valid_identifier():
    assert _IDENTIFIER.fullmatch(NAMESPACE)


def test_every_dataset_name_is_a_valid_identifier():
    for spec in DATASETS:
        assert _IDENTIFIER.fullmatch(spec.name), spec.name


def test_every_column_name_is_a_valid_identifier():
    for spec in DATASETS:
        for column in spec.columns:
            assert _IDENTIFIER.fullmatch(column.name), f"{spec.name}.{column.name}"


def test_every_dataset_lives_in_the_module_namespace():
    for spec in DATASETS:
        assert spec.namespace == NAMESPACE, spec.name


def test_every_dataset_declares_a_primary_key():
    # Advisory or not, a dataset without one cannot be upserted at all:
    # the adapter rejects mode="upsert" when primary_key is empty.
    for spec in DATASETS:
        assert spec.primary_key, f"{spec.name} declares no primary key"


def test_primary_key_columns_exist_in_the_schema():
    for spec in DATASETS:
        names = {column.name for column in spec.columns}
        for key in spec.primary_key:
            assert key in names, f"{spec.name}.{key} is not a column"


def test_partition_columns_exist_and_are_not_identifiers_of_a_row():
    # Partitioning on a per-row id would make one partition per row.
    for spec in DATASETS:
        names = {column.name for column in spec.columns}
        for partition in spec.partitions:
            assert partition.column in names, f"{spec.name}.{partition.column}"
            assert partition.column not in spec.primary_key, (
                f"{spec.name} partitions on its own primary key column "
                f"{partition.column!r}, which yields one partition per row"
            )


def test_dataset_names_are_unique():
    names = [spec.name for spec in DATASETS]
    assert len(names) == len(set(names))


def test_the_expected_datasets_are_declared():
    assert {spec.name for spec in DATASETS} == {
        "papers",
        "chunkers",
        "chunks",
        "prompts",
        "models",
        "extraction_runs",
        "extractions",
        "extracted_items",
        "projections",
        "run_requests",
        "input_locations",
        "pipelines",
    }
