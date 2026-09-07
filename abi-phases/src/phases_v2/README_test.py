"""The README documents behaviour, so it can go stale like anything else.

These check the parts that would mislead a reader if they drifted: the
datasets, the jobs, the layout, and the configuration default.
"""

import pathlib

from phases_v2 import PhasesV2Configuration
from phases_v2.datasets.schemas import DATASETS
from phases_v2.orchestrations.PhasesV2Orchestration import PhasesV2Orchestration

README = pathlib.Path(__file__).parent / "README.md"
MODULE = pathlib.Path(__file__).parent


def test_every_dataset_is_documented():
    text = README.read_text()

    for spec in DATASETS:
        assert f"`{spec.name}`" in text, spec.name


def test_every_dagster_job_is_documented():
    text = README.read_text()

    for job in PhasesV2Orchestration.New().definitions.jobs:
        assert job.name in text, job.name


def test_every_top_level_package_appears_in_the_layout():
    text = README.read_text()

    for path in MODULE.iterdir():
        if path.is_dir() and path.name != "__pycache__":
            assert f"{path.name}/" in text, path.name


def test_files_named_in_the_layout_exist():
    for name in ("identity.py", "sql.py", "datasets/schemas.py", "datasets/store.py"):
        assert (MODULE / name).is_file(), name


def test_the_documented_papers_root_default_is_the_real_one():
    default = PhasesV2Configuration.model_fields["papers_root"].default

    assert f'papers_root: "{default}"' in README.read_text()


def test_it_states_the_relationship_to_v1():
    # A reader landing here needs to know this module does not replace `phases`.
    text = README.read_text()

    assert "alongside" in text
    assert "not modified and not retired" in text
