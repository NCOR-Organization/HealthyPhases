"""Graph projection against the real dataset, with an in-memory triple sink.

The domain tests use fakes throughout; this checks the reads, the ledger and —
the part fakes cannot show — that pinning a snapshot really does hide a write
that lands mid-run.
"""

from datetime import UTC, datetime

import pytest
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2.datasets import store
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.store import ensure_datasets
from phases_v2.ontologies import vocabulary as v
from phases_v2.projection.adapters.secondary.DatasetExtractionReader import (
    DatasetExtractionReader,
)
from phases_v2.projection.factory import project_to_graph
from phases_v2.projection.fakes import FakeTripleSink


class _Services:
    def __init__(self, dataset):
        self.dataset = dataset

    def dataset_available(self) -> bool:
        return True


class _Engine:
    def __init__(self, dataset):
        self.services = _Services(dataset)


def _seed(rows, n=2, offset=0):
    now = datetime.now(UTC)
    rows.write_rows(
        "papers",
        [{"paper_id": f"p{i}", "file_name": f"{i}.pdf", "discovered_at": now}
         for i in range(offset, offset + n)],
    )
    rows.write_rows(
        "chunks",
        [{"chunk_id": f"c{i}", "paper_id": f"p{i}", "chunker_id": "w1", "seq": i,
          "text": f"chunk {i}"} for i in range(offset, offset + n)],
    )
    rows.write_rows(
        "extracted_items",
        [{"item_id": f"i{i}", "extraction_id": f"e{i}", "chunk_id": f"c{i}",
          "paper_id": f"p{i}", "prompt_id": "pr", "seq": 0, "text": f"claim {i}"}
         for i in range(offset, offset + n)],
    )
    rows.write_rows(
        "extractions",
        [{"extraction_id": f"e{i}", "chunk_id": f"c{i}", "model_id": "m",
          "prompt_id": "pr", "run_id": "r", "status": "succeeded",
          "response": {"results": [f"claim {i}"]}, "raw_response": "{}",
          "item_count": 1, "completed_at": now}
         for i in range(offset, offset + n)],
    )


@pytest.fixture
def engine(tmp_path):
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path / 'catalog.sqlite'}",
            data_path=str(tmp_path / "warehouse") + "/",
        )
    )
    ensure_datasets(dataset)
    _seed(DatasetRowStore(dataset))
    return _Engine(dataset)


def test_succeeded_extractions_are_projected(engine):
    sink = FakeTripleSink()

    report = project_to_graph(engine, sink=sink)

    assert report.projected == 2
    assert sink.count(str(v.EXTRACTIONS_GRAPH)) > 0
    assert sink.count(str(v.PAPERS_GRAPH)) > 0


def test_a_failed_extraction_is_not_projected(engine):
    DatasetRowStore(engine.services.dataset).write_rows(
        "extractions",
        [{"extraction_id": "bad", "chunk_id": "c0", "model_id": "m",
          "prompt_id": "pr", "run_id": "r", "status": "failed",
          "response": None, "raw_response": "oops", "item_count": 0,
          "completed_at": datetime.now(UTC)}],
    )
    sink = FakeTripleSink()

    project_to_graph(engine, sink=sink)

    assert v.extraction_uri("bad") not in {
        s for s, _p, _o in sink.graphs[str(v.EXTRACTIONS_GRAPH)]
    }


def test_re_running_projects_nothing_and_leaves_the_graph_identical(engine):
    sink = FakeTripleSink()
    project_to_graph(engine, sink=sink)
    before = {name: set(t) for name, t in sink.graphs.items()}

    report = project_to_graph(engine, sink=sink)

    assert report.projected == 0
    assert report.already_projected == 2
    assert {name: set(t) for name, t in sink.graphs.items()} == before


def test_only_new_extractions_are_projected_on_a_later_run(engine):
    sink = FakeTripleSink()
    project_to_graph(engine, sink=sink)
    _seed(DatasetRowStore(engine.services.dataset), n=1, offset=5)

    report = project_to_graph(engine, sink=sink)

    assert report.projected == 1


def test_the_ledger_records_what_was_projected(engine):
    project_to_graph(engine, sink=FakeTripleSink())

    rows = engine.services.dataset.query(
        "SELECT target, key FROM projections", namespace="phases_v2"
    ).rows
    assert {row["key"] for row in rows} == {"e0", "e1"}
    assert {row["target"] for row in rows} == {"graph"}


def test_a_pinned_reader_does_not_see_a_write_that_lands_after_it(engine):
    # This is the property fakes cannot demonstrate: the run reads the store as
    # of one snapshot, so a concurrent write is invisible to it and is picked
    # up by the next run instead of half-appearing in this one.
    live = DatasetRowStore(engine.services.dataset)
    pinned = DatasetExtractionReader(live.at_snapshot(live.snapshot()))
    before = len(pinned.succeeded_extractions())

    _seed(live, n=1, offset=9)

    assert len(pinned.succeeded_extractions()) == before
    assert len(DatasetExtractionReader(live).succeeded_extractions()) == before + 1


def test_an_extraction_is_never_seen_without_its_items(engine):
    live = DatasetRowStore(engine.services.dataset)
    pinned = DatasetExtractionReader(live.at_snapshot(live.snapshot()))

    extractions = pinned.succeeded_extractions()
    items = pinned.items_for([e["extraction_id"] for e in extractions])

    assert {i["extraction_id"] for i in items} == {
        e["extraction_id"] for e in extractions
    }


def test_the_graph_is_rebuildable_from_the_datasets_alone(engine):
    first = FakeTripleSink()
    project_to_graph(engine, sink=first)

    # Clear the ledger, as dropping and rebuilding the graph would.
    store.truncate(engine.services.dataset, "projections")
    second = FakeTripleSink()
    project_to_graph(engine, sink=second)

    assert {n: set(t) for n, t in second.graphs.items()} == {
        n: set(t) for n, t in first.graphs.items()
    }
