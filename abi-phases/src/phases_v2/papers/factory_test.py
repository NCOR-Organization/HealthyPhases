"""Paper ingestion against the real object storage and dataset services.

The domain tests use fakes; this one checks the wiring — that recursive
listing, PDF rendering and the ``papers`` dataset actually fit together, and
that a second run costs nothing.
"""

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

from phases_v2.datasets.schemas import NAMESPACE
from phases_v2.datasets.store import ensure_datasets
from phases_v2.papers.factory import ingest_papers


def _pdf(text: str) -> bytes:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text, fontsize=14)
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
    return _Engine(storage, dataset)


def _seed_corpus(engine):
    storage = engine.services.object_storage
    storage.put_object("papers", "root.pdf", _pdf("Root paper on solitude"))
    storage.put_object("papers", "2024/spring.pdf", _pdf("Spring paper on solitude"))
    storage.put_object(
        "papers", "2024/q1/january.pdf", _pdf("January paper on solitude")
    )


def _paper_rows(engine):
    return engine.services.dataset.query(
        "SELECT paper_id, storage_key, file_name, text_key, size_bytes "
        "FROM papers ORDER BY storage_key",
        namespace=NAMESPACE,
    ).rows


def test_a_nested_corpus_is_ingested_and_recorded(engine):
    _seed_corpus(engine)

    report = ingest_papers(engine, ["papers"])

    assert report.discovered == 3
    assert report.ingested == 3
    assert report.failed == 0
    rows = _paper_rows(engine)
    assert [row["storage_key"] for row in rows] == [
        "2024/q1/january.pdf",
        "2024/spring.pdf",
        "root.pdf",
    ]
    assert all(row["text_key"] for row in rows)
    assert all(row["size_bytes"] > 0 for row in rows)


def test_the_rendered_text_is_stored_and_reachable(engine):
    _seed_corpus(engine)

    ingest_papers(engine, ["papers"])

    row = next(r for r in _paper_rows(engine) if r["storage_key"] == "root.pdf")
    text = engine.services.object_storage.get_object(
        "phases_v2_text", row["text_key"]
    ).decode()
    assert "Root paper on solitude" in text


def test_re_running_adds_no_rows_and_renders_nothing(engine):
    _seed_corpus(engine)
    ingest_papers(engine, ["papers"])
    before = _paper_rows(engine)

    report = ingest_papers(engine, ["papers"])

    assert report.ingested == 0
    assert report.skipped == 3
    assert _paper_rows(engine) == before


def test_a_new_paper_is_picked_up_on_a_later_run(engine):
    _seed_corpus(engine)
    ingest_papers(engine, ["papers"])

    engine.services.object_storage.put_object(
        "papers", "2025/late.pdf", _pdf("Late paper on solitude")
    )
    report = ingest_papers(engine, ["papers"])

    assert report.ingested == 1
    assert report.skipped == 3
    assert len(_paper_rows(engine)) == 4


def test_a_missing_location_does_not_stop_the_others(engine):
    _seed_corpus(engine)

    report = ingest_papers(engine, ["nowhere", "papers"])

    assert "nowhere" in report.failed_locations
    assert report.ingested == 3


def test_the_same_paper_under_two_paths_is_recorded_once(engine):
    identical = _pdf("Duplicated paper on solitude")
    engine.services.object_storage.put_object("papers", "a/copy.pdf", identical)
    engine.services.object_storage.put_object("papers", "b/copy.pdf", identical)

    report = ingest_papers(engine, ["papers"])

    assert report.discovered == 2
    assert len(_paper_rows(engine)) == 1
