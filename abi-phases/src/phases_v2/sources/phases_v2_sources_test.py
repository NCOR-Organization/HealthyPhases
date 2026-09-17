from types import SimpleNamespace
from uuid import uuid4

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


def test_query_summaries_count_distinct_papers_and_scope_ingestion_dates(dataset):
    publisher, request, _engine = setup(dataset)
    store = publisher.store
    completed = publisher.one("run_requests", request_id=request["request_id"])
    store.save(
        "run_requests", [dict(completed, finished_at="2026-01-01T10:00:00+00:00")]
    )
    # Versions and repeated requests must not multiply the number of papers.
    artifact = store.rows("artifacts")[0]
    store.save("artifacts", [dict(artifact, artifact_id="another-version")])
    for status, finished in [
        ("partial", "2026-01-02T10:00:00+00:00"),
        ("failed", "2026-01-03T10:00:00+00:00"),
        ("pending", ""),
    ]:
        store.save(
            "run_requests",
            [
                dict(
                    completed,
                    request_id=str(uuid4()),
                    status=status,
                    finished_at=finished,
                )
            ],
        )
    shared = publisher.search({"query": "solitude"})["query"]
    publisher.source.search = lambda parameters: (1, [{"pmid": "3", "pmcid": "PMC3"}])
    unpublished = publisher.search({"query": "solitude"})["query"]
    summaries = {q["query_id"]: q for q in PubmedCatalog(dataset).queries()["queries"]}
    assert summaries[request["query_id"]]["published_paper_count"] == 2
    assert (
        summaries[request["query_id"]]["last_ingested_at"]
        == "2026-01-02T10:00:00+00:00"
    )
    assert summaries[shared["query_id"]]["published_paper_count"] == 2
    assert summaries[shared["query_id"]]["last_ingested_at"] == ""
    assert summaries[unpublished["query_id"]]["published_paper_count"] == 0
    assert summaries[unpublished["query_id"]]["last_ingested_at"] == ""

    # A later ingestion that reuses PDFs still has its own completion date.
    reuse = publisher.submit({"query_id": shared["query_id"]})
    reused = publisher.execute(reuse["request_id"], "reuse-run")
    store.save("run_requests", [dict(reused, finished_at="2026-02-01T10:00:00+00:00")])
    summaries = {q["query_id"]: q for q in PubmedCatalog(dataset).queries()["queries"]}
    assert (
        summaries[shared["query_id"]]["last_ingested_at"] == "2026-02-01T10:00:00+00:00"
    )
    assert len(publisher.source.calls) == 2


def test_query_summary_contract_rejects_negative_paper_counts():
    from phases_v2.app.contracts.app_validation import validate_command

    with pytest.raises(ValueError):
        validate_command(
            "PubmedQuerySummary",
            {"query_id": str(uuid4()), "published_paper_count": -1},
        )


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
