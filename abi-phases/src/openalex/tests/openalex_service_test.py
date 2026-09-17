from uuid import uuid4

import pytest

from openalex.adapters.secondary.openalex_dataset_store import OpenalexDatasetStore
from openalex.adapters.secondary.openalex_pubmed_catalog import PubmedCatalog
from openalex.application.openalex_service import OpenalexService
from openalex.domain.openalex_errors import AlreadyClaimed, OpenalexUnavailable
from pubmed.adapters.secondary.pubmed_dataset_store import PubmedDatasetStore
from pubmed.application.pubmed_service import PubmedService


def raw(pmid, doi="", work=None):
    return {
        "id": f"https://openalex.org/{work or 'W' + pmid}",
        "ids": {"pmid": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "doi": doi},
        "doi": doi,
        "display_name": "Paper",
        "cited_by_count": 42,
        "topics": [{"id": "T1", "display_name": "Mental health", "score": 0.9}],
        "authorships": [
            {
                "author": {"display_name": "A"},
                "institutions": [
                    {"display_name": "Paris University", "country_code": "FR"}
                ],
            }
        ],
    }


class Source:
    api_key = ""

    def __init__(self):
        self.calls = []
        self.fail_on = ""

    def lookup(self, identifier, before_request):
        before_request()
        self.calls.append(identifier)
        if identifier == self.fail_on:
            raise OpenalexUnavailable("Temporarily unavailable")
        return raw(identifier.split(":")[1])


def setup(dataset, count=3, **options):
    pubmed = PubmedDatasetStore(dataset)
    pubmed.ensure()
    query_id = str(uuid4())
    pubmed.save(
        "queries",
        [
            {
                "query_id": query_id,
                "query": "solitude",
                "created_at": "2026-09-17T00:00:00+00:00",
                "contract_version": 1,
            }
        ],
    )
    pubmed.save(
        "papers", [{"pmid": str(i), "title": f"Paper {i}"} for i in range(1, count + 1)]
    )
    pubmed.save(
        "query_papers",
        [{"query_id": query_id, "pmid": str(i)} for i in range(1, count + 1)],
    )
    store = OpenalexDatasetStore(dataset)
    store.ensure()
    service = OpenalexService(store, PubmedCatalog(dataset), Source(), **options)
    return service, pubmed, query_id


def drain(service, row):
    while row["status"] == "pending":
        row = service.execute(row["request_id"], row["generation"], "worker")
    return row


def test_snapshot_all_records_without_pdfs_and_cross_dataset_filters(dataset):
    service, pubmed, query = setup(dataset, batch_size=2)
    row = service.create({"query_id": query})
    assert row["total"] == 3 and not service.source.calls
    pubmed.save("papers", [{"pmid": "4", "title": "Arrived later"}])
    pubmed.save("query_papers", [{"query_id": query, "pmid": "4"}])
    row = drain(service, row)
    assert (
        row["status"] == "succeeded" and row["processed"] == 3 and row["enriched"] == 3
    )
    assert service.source.calls == ["pmid:1", "pmid:2", "pmid:3"]
    assert not pubmed.rows("artifacts")
    assert service.detail("1")["work"]["citation_count"] == 42
    browser = PubmedService(pubmed, None, None)
    results = browser.browse_papers(
        {
            "status": "all",
            "topic": "MENTAL",
            "institution": "Paris",
            "min_citations": 40,
        }
    )
    assert results["total"] == 3
    assert results["papers"][0]["openalex"]["status"] == "enriched"
    assert (
        browser.browse_papers({"status": "all", "enrichment_status": "not_enriched"})[
            "total"
        ]
        == 1
    )
    assert (
        browser.browse_papers({"status": "all", "topic": "' OR TRUE --"})["total"] == 0
    )
    service.store.ensure()
    again = drain(service, service.create({"query_id": query}))
    assert again["cached"] == 3 and again["http_attempts"] == 1


def test_failure_resume_budget_and_stale_workers(dataset):
    service, pubmed, query = setup(dataset, request_budget=2, batch_size=1)
    row = service.create({"query_id": query})
    first = service.execute(row["request_id"], 0, "old")
    assert first["processed"] == 1 and first["status"] == "pending"
    assert service.execute(row["request_id"], 0, "stale") is None
    assert service.fail(row["request_id"], 0, "old", "late error") is None
    failed = drain(service, first)
    assert (
        failed["status"] == "failed"
        and failed["processed"] == 2
        and failed["http_attempts"] == 2
    )
    assert "allowance" in failed["error"]
    with pytest.raises(AlreadyClaimed):
        service.store.save_owned("paper_enrichments", [], {**first, "run_id": "old"})
    resumed = drain(service, service.resume(row["request_id"]))
    assert resumed["status"] == "succeeded" and resumed["http_attempts"] == 3
    assert service.source.calls == ["pmid:1", "pmid:2", "pmid:3"]


def test_result_checkpoint_survives_crash_without_refetch(dataset, monkeypatch):
    service, pubmed, query = setup(dataset, count=1)
    row = service.create({"query_id": query, "force_refresh": True})
    original = service.store.update_request

    def crash_after_result(request_id, change):
        if change.__name__ == "progress":
            raise RuntimeError("worker stopped")
        return original(request_id, change)

    monkeypatch.setattr(service.store, "update_request", crash_after_result)
    with pytest.raises(RuntimeError):
        service.execute(row["request_id"], 0, "stopped")
    monkeypatch.setattr(service.store, "update_request", original)
    final = drain(service, service.resume(row["request_id"]))
    assert final["processed"] == final["enriched"] == final["http_attempts"] == 1


def test_refresh_failure_preserves_last_known_metadata(dataset):
    service, pubmed, query = setup(dataset, count=1)
    drain(service, service.create({"query_id": query}))
    service.source.fail_on = "pmid:1"
    failed = drain(service, service.create({"query_id": query, "force_refresh": True}))
    assert failed["status"] == "failed"
    detail = service.detail("1")
    assert (
        detail["enrichment"]["status"] == "failed"
        and detail["enrichment"]["work_id"] == "W1"
    )
    assert detail["work"]["citation_count"] == 42


def test_worker_publication_fenced_against_concurrent_cancellation(
    dataset, monkeypatch
):
    service, pubmed, query = setup(dataset, count=1)
    created = service.create({"query_id": query})
    owner = service.store.update_request(
        created["request_id"],
        lambda row: {**row, "status": "running", "run_id": "worker"},
    )
    original = dataset.write
    interrupted = False

    def cancel_before_write(table, records, **kwargs):
        nonlocal interrupted
        if table == "paper_enrichments" and not interrupted:
            interrupted = True
            service.fail(created["request_id"], 0, "worker", "Canceled")
        return original(table, records, **kwargs)

    monkeypatch.setattr(dataset, "write", cancel_before_write)
    with pytest.raises(AlreadyClaimed):
        service.store.save_owned(
            "paper_enrichments",
            [{"pmid": "1", "status": "no_match", "contract_version": 1}],
            owner,
        )
    assert service.store.rows("paper_enrichments") == []


def test_concurrent_claims_process_a_request_once(dataset):
    from concurrent.futures import ThreadPoolExecutor

    service, pubmed, query = setup(dataset, count=1)
    created = service.create({"query_id": query})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda run: service.execute(created["request_id"], 0, run),
                ["one", "two"],
            )
        )
    assert sum(row is not None for row in results) == 1
    assert service.source.calls == ["pmid:1"]


def test_ambiguous_and_absent_matches_finish_without_linking_the_wrong_work(dataset):
    service, pubmed, query = setup(dataset, count=2)

    def lookup(identifier, before_request):
        before_request()
        return raw("999") if identifier == "pmid:1" else None

    service.source.lookup = lookup
    final = drain(service, service.create({"query_id": query}))
    assert final["status"] == "partial" and final["ambiguous"] == final["no_match"] == 1
    assert service.store.rows("works") == []
    assert service.detail("1")["enrichment"]["candidate_ids"] == ["W999"]
