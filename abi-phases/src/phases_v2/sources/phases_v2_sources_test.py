from types import SimpleNamespace

import pytest

from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.store import ensure_datasets
from phases_v2.papers.factory import ingest_papers
from phases_v2.requests.factory import request_store
from phases_v2.sources.adapters.secondary.phases_v2_pubmed_catalog import PubmedCatalog
from phases_v2.sources.phases_v2_sources import manifest_for, submit_pubmed
from pubmed.adapters.secondary.pubmed_dataset_store import PubmedDatasetStore
from pubmed.application.pubmed_service import PubmedService
from pubmed.tests.pubmed_service_test import FakeSource, MemoryStorage, queue


def setup(dataset):
    store = PubmedDatasetStore(dataset)
    store.ensure()
    storage = MemoryStorage()
    publisher = PubmedService(store, FakeSource(), storage)
    row = queue(publisher)
    publisher.execute(row["request_id"], "run")
    ensure_datasets(dataset)
    engine = SimpleNamespace(
        services=SimpleNamespace(dataset=dataset, object_storage=storage)
    )
    return publisher, row, engine


def test_absent_publisher_is_available_as_an_empty_optional_source(dataset):
    catalog = PubmedCatalog(dataset)
    assert catalog.queries() == {"available": False, "queries": []}
    assert catalog.artifacts("anything") == []


def test_manual_manifest_does_not_expand_with_later_publication(dataset):
    publisher, query, engine = setup(dataset)
    catalog = PubmedCatalog(dataset)
    assert catalog.queries()["available"]
    rows = DatasetRowStore(dataset)
    request = submit_pubmed(
        rows,
        request_store(engine),
        catalog,
        {
            "query_id": query["query_id"],
            "chunker_id": "chunker",
            "prompt_ids": ["prompt"],
            "model_id": "model",
        },
    )
    manifest = manifest_for(rows, request.request_id)
    assert len(manifest) == 2
    artifact = publisher.store.rows("artifacts")[0]
    publisher.store.save(
        "artifacts",
        [dict(artifact, artifact_id="later-version", storage_key="later.pdf")],
    )
    assert len(catalog.artifacts(query["query_id"])) == 3
    assert len(manifest_for(rows, request.request_id)) == 2
    assert request_store(engine).get(request.request_id).status == "pending"


def test_selected_artifact_is_verified_and_only_selected_objects_are_read(
    dataset, monkeypatch
):
    _publisher, query, engine = setup(dataset)
    artifacts = PubmedCatalog(dataset).artifacts(query["query_id"])[:1]
    engine.services.object_storage.put_object(
        "pubmed/papers", "unrelated.pdf", b"unrelated"
    )
    from phases_v2.papers.adapters.secondary.PdfTextRenderer import PdfTextRenderer

    monkeypatch.setattr(
        PdfTextRenderer, "render", lambda self, content, name: "Rendered text"
    )
    report = ingest_papers(engine, ["pubmed/papers"], artifacts=artifacts)
    assert report.ingested == 1
    assert report.paper_ids == [artifacts[0]["content_sha256"]]
    engine.services.object_storage.put_object(
        artifacts[0]["storage_prefix"], artifacts[0]["storage_key"], b"changed"
    )
    with pytest.raises(ValueError, match="checksum"):
        ingest_papers(engine, ["pubmed/papers"], artifacts=artifacts)


def test_empty_published_selection_never_queues_work(dataset):
    _publisher, _query, engine = setup(dataset)
    with pytest.raises(ValueError, match="no published"):
        submit_pubmed(
            DatasetRowStore(dataset),
            request_store(engine),
            PubmedCatalog(dataset),
            {
                "query_id": "00000000-0000-4000-8000-000000000000",
                "chunker_id": "chunker",
                "prompt_ids": ["prompt"],
                "model_id": "model",
            },
        )
    assert request_store(engine).pending() == []


def test_projector_reader_limits_all_reads_to_selected_papers(dataset):
    from phases_v2.projection.adapters.secondary.DatasetExtractionReader import (
        DatasetExtractionReader,
    )

    ensure_datasets(dataset)
    rows = DatasetRowStore(dataset)
    for paper in ["selected", "other"]:
        rows.write_rows("papers", [{"paper_id": paper, "file_name": paper + ".pdf"}])
        rows.write_rows(
            "chunks", [{"chunk_id": paper, "paper_id": paper, "text": paper}]
        )
        rows.write_rows(
            "extractions",
            [{"extraction_id": paper, "chunk_id": paper, "status": "succeeded"}],
        )
    reader = DatasetExtractionReader(rows, paper_ids=["selected"])
    assert [p["paper_id"] for p in reader.papers()] == ["selected"]
    assert [p["paper_id"] for p in reader.chunks()] == ["selected"]
    assert [p["extraction_id"] for p in reader.succeeded_extractions()] == ["selected"]
    empty = DatasetExtractionReader(rows, paper_ids=[])
    assert empty.papers() == empty.chunks() == empty.succeeded_extractions() == []
