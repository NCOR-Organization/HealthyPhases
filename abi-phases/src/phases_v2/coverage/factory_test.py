"""Wiring the report: what it checks by default, on a real empty catalog."""

from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2.chunking.chunkers import WINDOW_512_128
from phases_v2.coverage.factory import coverage_report, selection
from phases_v2.coverage.interfaces import DEFAULT_MODEL, EVERYTHING, TARGETS
from phases_v2.datasets.store import ensure_datasets
from phases_v2.prompts.templates import current_prompts


def test_by_default_it_checks_the_current_prompts_with_the_default_model():
    chosen = selection()

    assert chosen.models == (DEFAULT_MODEL,)
    assert chosen.prompt_ids == tuple(p.prompt_id for p in current_prompts())
    assert len(chosen.prompt_ids) == 8
    assert chosen.chunker_id == WINDOW_512_128.chunker_id


def test_repeated_choices_replace_the_defaults_once_each():
    chosen = selection(["a", "b", "a"], ["p1", "p1"], "chunker")

    assert (chosen.models, chosen.prompt_ids, chosen.chunker_id) == (
        ("a", "b"),
        ("p1",),
        "chunker",
    )


def test_an_empty_catalog_reports_nothing_held_and_writes_nothing(tmp_path):
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path / 'catalog.sqlite'}",
            data_path=str(tmp_path / "data") + "/",
        )
    )
    ensure_datasets(dataset)
    snapshots = len(dataset.list_snapshots())

    report = coverage_report(dataset, object_storage=None, chosen=selection())

    [everything] = report.sources
    assert everything.kind == EVERYTHING
    assert everything.documents == []
    assert [b.target for b in report.backlog] == list(TARGETS)
    assert report.problems() == []
    assert len(dataset.list_snapshots()) == snapshots
