"""Extraction against the real dataset, with a stubbed model.

Covers what the fakes cannot: that the JSON response is stored as a queryable
value, that runs are recorded, and that an undeclared model or prompt is
refused before anything is written.
"""

import json

import pytest
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2.chunking.chunkers import WINDOW_512_128
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.schemas import NAMESPACE
from phases_v2.datasets.store import ensure_datasets
from phases_v2.extraction.factory import extract, resolve_prompt
from phases_v2.extraction.fakes import FakeModel
from phases_v2.models.catalog import DECLARED_MODELS, UnknownModelError
from phases_v2.prompts.templates import declared_prompts

MODEL_ID = DECLARED_MODELS[0].model_id
PROMPT = declared_prompts()[0]


class _Services:
    def __init__(self, dataset):
        self.dataset = dataset

    def dataset_available(self) -> bool:
        return True


class _Engine:
    def __init__(self, dataset):
        self.services = _Services(dataset)


@pytest.fixture
def engine(tmp_path):
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path / 'catalog.sqlite'}",
            data_path=str(tmp_path / "warehouse") + "/",
        )
    )
    ensure_datasets(dataset)
    DatasetRowStore(dataset).write_rows(
        "chunks",
        [
            {
                "chunk_id": f"c{i}",
                "paper_id": f"p{i % 2}",
                "chunker_id": WINDOW_512_128.chunker_id,
                "seq": i,
                "text": f"Solitude passage {i}",
            }
            for i in range(4)
        ],
    )
    return _Engine(dataset)


def _query(engine, sql):
    return engine.services.dataset.query(sql, namespace=NAMESPACE).rows


def _run(engine, model=None, **kwargs):
    return extract(
        engine,
        model_id=MODEL_ID,
        prompt_id=PROMPT.prompt_id,
        model=model or FakeModel(json.dumps({PROMPT.output_key: ["one", "two"]})),
        **kwargs,
    )


def test_a_run_extracts_every_chunk_and_records_the_items(engine):
    report = _run(engine)

    assert report.succeeded == 4
    assert len(_query(engine, "SELECT extraction_id FROM extractions")) == 4
    assert len(_query(engine, "SELECT item_id FROM extracted_items")) == 8


def test_the_response_is_stored_as_a_queryable_value_not_an_opaque_string(engine):
    _run(engine)

    # The point of the json column: ask the store a question about the model's
    # output without parsing anything in Python first.
    rows = _query(
        engine,
        "SELECT extraction_id FROM extractions "
        f"WHERE json_array_length(response->'{PROMPT.output_key}') > 1",
    )

    assert len(rows) == 4


def test_the_stored_response_round_trips_as_structured_data(engine):
    _run(engine)

    [row] = _query(engine, "SELECT response FROM extractions LIMIT 1")

    assert row["response"] == {PROMPT.output_key: ["one", "two"]}


def test_re_running_costs_no_model_calls(engine):
    _run(engine)
    model = FakeModel(json.dumps({PROMPT.output_key: ["one"]}))

    report = _run(engine, model=model)

    assert model.prompts == []
    assert report.executed == 0
    assert report.skipped == 4


def test_the_run_is_recorded_with_its_scope_and_counts(engine):
    report = _run(engine)

    [run] = _query(
        engine,
        "SELECT run_id, chunker_id, model_id, prompt_id, succeeded, failed, skipped "
        "FROM extraction_runs",
    )
    assert run["run_id"] == report.run_id
    assert run["chunker_id"] == WINDOW_512_128.chunker_id
    assert run["model_id"] == MODEL_ID
    assert run["prompt_id"] == PROMPT.prompt_id
    assert run["succeeded"] == 4


def test_a_failure_is_recorded_and_the_others_still_succeed(engine):
    report = _run(
        engine,
        model=FakeModel(
            json.dumps({PROMPT.output_key: ["one"]}),
            fail_on={"Solitude passage 2"},
        ),
    )

    assert (report.succeeded, report.failed) == (3, 1)
    [failed] = _query(
        engine, "SELECT chunk_id, error FROM extractions WHERE status = 'failed'"
    )
    assert failed["chunk_id"] == "c2"
    assert failed["error"]


def test_a_failure_keeps_the_raw_response_for_re_parsing(engine):
    _run(engine, model=FakeModel("not json at all"))

    [row] = _query(
        engine,
        "SELECT response, raw_response FROM extractions "
        "WHERE status = 'failed' LIMIT 1",
    )
    assert row["response"] is None
    assert row["raw_response"] == "not json at all"


def test_a_run_can_be_limited(engine):
    report = _run(engine, max_chunks=2)

    assert report.executed == 2


def test_a_run_can_be_scoped_to_papers(engine):
    _run(engine, paper_ids=["p0"])

    rows = _query(engine, "SELECT chunk_id FROM extractions ORDER BY chunk_id")
    assert [row["chunk_id"] for row in rows] == ["c0", "c2"]


def test_an_undeclared_model_is_refused_before_anything_is_written(engine):
    with pytest.raises(UnknownModelError):
        extract(
            engine,
            model_id="nobody/declared-this",
            prompt_id=PROMPT.prompt_id,
            model=FakeModel(),
        )

    assert _query(engine, "SELECT extraction_id FROM extractions") == []
    assert _query(engine, "SELECT run_id FROM extraction_runs") == []


def test_an_undeclared_prompt_is_refused_before_anything_is_written(engine):
    with pytest.raises(ValueError, match="not a declared prompt"):
        extract(
            engine,
            model_id=MODEL_ID,
            prompt_id="nobody_declared_this",
            model=FakeModel(),
        )

    assert _query(engine, "SELECT extraction_id FROM extractions") == []


def test_resolving_a_declared_prompt_returns_it():
    assert resolve_prompt(PROMPT.prompt_id) == PROMPT


def test_items_carry_the_prompt_so_they_share_the_extraction_partition(engine):
    _run(engine)

    rows = _query(engine, "SELECT DISTINCT prompt_id FROM extracted_items")
    assert [row["prompt_id"] for row in rows] == [PROMPT.prompt_id]


def test_a_caller_can_supply_the_run_id_so_it_can_find_its_own_counts(engine):
    _run(engine, run_id="req-42")

    [run] = _query(engine, "SELECT run_id, succeeded FROM extraction_runs")
    assert run["run_id"] == "req-42"
    assert run["succeeded"] == 4


def test_without_one_a_run_id_is_generated(engine):
    report = _run(engine)

    [run] = _query(engine, "SELECT run_id FROM extraction_runs")
    assert run["run_id"] == report.run_id
    assert run["run_id"]
