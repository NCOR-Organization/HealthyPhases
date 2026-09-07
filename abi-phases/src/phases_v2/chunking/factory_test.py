"""Chunking against the real object storage and dataset services."""

import pytest
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService
from naas_abi_core.services.object_storage.adapters.secondary.ObjectStorageSecondaryAdapterFS import (
    ObjectStorageSecondaryAdapterFS,
)
from naas_abi_core.services.object_storage.ObjectStorageService import (
    ObjectStorageService,
)

from phases_v2.chunking.chunkers import WINDOW_512_128
from phases_v2.chunking.factory import chunk_corpus, mechanism_for, resolve_chunker
from phases_v2.chunking.registry import Chunker
from phases_v2.datasets.schemas import NAMESPACE
from phases_v2.datasets.store import ensure_datasets
from phases_v2.papers.factory import ingest_papers


def _pdf(text: str) -> bytes:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    return document.tobytes()


class _Services:
    def __init__(self, object_storage, dataset):
        self.object_storage = object_storage
        self.dataset = dataset

    def dataset_available(self) -> bool:
        return True


class _Engine:
    def __init__(self, object_storage, dataset):
        self.services = _Services(object_storage, dataset)


@pytest.fixture
def engine(tmp_path):
    storage = ObjectStorageService(
        adapter=ObjectStorageSecondaryAdapterFS(base_path=str(tmp_path / "objects"))
    )
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path / 'catalog.sqlite'}",
            data_path=str(tmp_path / "warehouse") + "/",
        )
    )
    ensure_datasets(dataset)
    engine = _Engine(storage, dataset)
    storage.put_object("papers", "a.pdf", _pdf("Solitude is a state of being alone."))
    storage.put_object("papers", "b/c.pdf", _pdf("Loneliness differs from solitude."))
    ingest_papers(engine, ["papers"])
    return engine


def _chunks(engine, **where):
    clause = ""
    if where:
        clause = " WHERE " + " AND ".join(
            f"{column} = '{value}'" for column, value in where.items()
        )
    return engine.services.dataset.query(
        f"SELECT chunk_id, paper_id, chunker_id, seq, text FROM chunks{clause}",
        namespace=NAMESPACE,
    ).rows


def test_the_ingested_corpus_is_chunked(engine):
    report = chunk_corpus(engine)

    assert report.papers_chunked == 2
    assert report.chunks_written >= 2
    rows = _chunks(engine)
    assert {row["chunker_id"] for row in rows} == {WINDOW_512_128.chunker_id}
    assert all(row["text"] for row in rows)


def test_chunks_reference_the_papers_they_came_from(engine):
    chunk_corpus(engine)

    paper_ids = {
        row["paper_id"]
        for row in engine.services.dataset.query(
            "SELECT paper_id FROM papers", namespace=NAMESPACE
        ).rows
    }
    assert {row["paper_id"] for row in _chunks(engine)} <= paper_ids


def test_re_running_writes_nothing_and_reads_no_text(engine):
    chunk_corpus(engine)
    before = sorted(row["chunk_id"] for row in _chunks(engine))

    report = chunk_corpus(engine)

    assert report.papers_considered == 0
    assert report.chunks_written == 0
    assert sorted(row["chunk_id"] for row in _chunks(engine)) == before


def test_a_second_mechanism_coexists_with_the_first(engine):
    chunk_corpus(engine)
    tiny = Chunker(
        name="window", version="1", params={"size": 5, "overlap": 1, "unit": "whitespace_token"}
    )

    chunk_corpus(engine, chunker=tiny)

    assert {row["chunker_id"] for row in _chunks(engine)} == {
        WINDOW_512_128.chunker_id,
        tiny.chunker_id,
    }
    assert len(_chunks(engine, chunker_id=tiny.chunker_id)) > len(
        _chunks(engine, chunker_id=WINDOW_512_128.chunker_id)
    )


def test_a_run_can_be_scoped_to_one_paper(engine):
    [first] = engine.services.dataset.query(
        "SELECT paper_id FROM papers ORDER BY paper_id LIMIT 1", namespace=NAMESPACE
    ).rows

    report = chunk_corpus(engine, paper_ids=[first["paper_id"]])

    assert report.papers_chunked == 1
    assert {row["paper_id"] for row in _chunks(engine)} == {first["paper_id"]}


def test_scoping_to_no_papers_does_nothing_rather_than_everything(engine):
    report = chunk_corpus(engine, paper_ids=[])

    assert report.papers_considered == 0
    assert _chunks(engine) == []


def test_a_paper_id_containing_a_quote_cannot_break_the_query(engine):
    # Ids are hashes today, but the query builder must not depend on that.
    report = chunk_corpus(engine, paper_ids=["x' OR '1'='1"])

    assert report.papers_considered == 0


def test_resolving_a_declared_chunker_returns_it(engine):
    assert resolve_chunker(WINDOW_512_128.chunker_id) is WINDOW_512_128


def test_resolving_an_unknown_chunker_is_rejected(engine):
    with pytest.raises(ValueError, match="not a declared chunker"):
        resolve_chunker("nope")


def test_the_declared_chunker_builds_the_v1_window(engine):
    mechanism = mechanism_for(WINDOW_512_128)

    assert mechanism._size == 512
    assert mechanism._overlap == 128
