from copy import deepcopy
from hashlib import sha256
from typing import ClassVar

import pytest

from pubmed.application.pubmed_service import PubmedService
from pubmed.domain.pubmed_errors import (
    AcquisitionError,
    FullTextUnavailable,
    RequestAlreadyClaimed,
)


class MemoryStore:
    keys: ClassVar[dict] = {
        "queries": ("query_id",),
        "papers": ("pmid",),
        "query_papers": ("query_id", "pmid"),
        "artifacts": ("artifact_id",),
        "run_requests": ("request_id",),
        "schedules": ("schedule_id",),
    }

    def __init__(self):
        self.tables = {name: {} for name in self.keys}

    def rows(self, table, **filters):
        return [
            deepcopy(row)
            for row in self.tables[table].values()
            if all(row.get(k) == v for k, v in filters.items())
        ]

    def save(self, table, records):
        for row in records:
            self.tables[table][tuple(row[k] for k in self.keys[table])] = deepcopy(row)

    def claim(self, request_id, run_id):
        row = self.rows("run_requests", request_id=request_id)[0]
        if row["status"] != "pending":
            raise RequestAlreadyClaimed(request_id)
        row.update(status="running", run_id=run_id)
        self.save("run_requests", [row])
        return row

    def update_schedule(self, schedule_id, change):
        from pubmed.domain.pubmed_errors import PublicationNotFound

        rows = self.rows("schedules", schedule_id=schedule_id)
        if not rows:
            raise PublicationNotFound(schedule_id)
        row = change(rows[0])
        self.save("schedules", [row])
        return row


class MemoryStorage:
    def __init__(self):
        self.files = {}

    def put_object(self, prefix, key, content):
        self.files[prefix, key] = content

    def get_object(self, prefix, key):
        if (prefix, key) not in self.files:
            raise FileNotFoundError(key)
        return self.files[prefix, key]


class FakeSource:
    def __init__(self):
        self.calls = []
        self.fail = set()

    def search(self, parameters):
        return 2, [
            {
                "pmid": p,
                "pmcid": "PMC" + p,
                "title": "Paper " + p,
                "doi": "",
                "journal": "",
                "publication_date": "",
                "authors": [],
            }
            for p in ("1", "2")
        ]

    def download(self, pmcid):
        self.calls.append(pmcid)
        if pmcid in self.fail:
            raise FullTextUnavailable("No PDF")
        return b"%PDF-1.7 " + pmcid.encode(), {
            "version": pmcid + ".1",
            "source_url": "https://example.test/paper.pdf",
        }


@pytest.fixture
def service():
    return PubmedService(MemoryStore(), FakeSource(), MemoryStorage())


def queue(service):
    query = service.search({"query": "solitude"})["query"]
    return service.submit({"query_id": query["query_id"]})


def test_search_only_saves_metadata_and_queue_is_durable(service):
    row = queue(service)
    assert row["status"] == "pending"
    assert not service.source.calls
    assert not service.storage.files
    assert len(service.queries()) == 1
    assert len(service.papers(row["query_id"])) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"query": " "},
        {"query": "q", "max_results": 0},
        {"query": "q", "max_results": 1001},
        {"query": "q", "start_date": "2026-02-30"},
        {"query": "q", "start_date": "2026-05-01", "end_date": "2026-01-01"},
        {"query": "q", "unknown": True},
        {"query": "q", "sort": "invalid"},
    ],
)
def test_invalid_searches_execute_protovalidate_before_acquisition(service, payload):
    with pytest.raises(ValueError):
        service.search(payload)
    assert not service.store.rows("queries")


def test_publication_is_deduplicated_across_queries(service):
    first, second = queue(service), queue(service)
    service.execute(first["request_id"], "run-1")
    service.execute(second["request_id"], "run-2")
    assert len(service.store.rows("artifacts")) == 2
    assert len(service.source.calls) == 2
    for artifact in service.store.rows("artifacts"):
        content = service.storage.get_object(
            artifact["storage_prefix"], artifact["storage_key"]
        )
        assert artifact["content_sha256"] == sha256(content).hexdigest()
    assert len(service.papers(second["query_id"])[0]["artifacts"]) == 1


def test_partial_failure_is_visible_and_retry_only_requests_remaining(service):
    service.source.fail = {"PMC2"}
    request = queue(service)
    finished = service.execute(request["request_id"], "run-1")
    assert finished["status"] == "partial"
    assert finished["outcomes"]["2"]["status"] == "unavailable"
    retry = service.retry(request["request_id"])
    assert retry["pmids"] == ["2"]
    service.source.fail.clear()
    assert service.execute(retry["request_id"], "run-2")["status"] == "succeeded"
    assert service.source.calls == ["PMC1", "PMC2", "PMC2"]


def test_storage_failure_never_publishes_ready(service):
    def fail(*args):
        raise AcquisitionError("Storage unavailable")

    service.storage.put_object = fail
    result = service.execute(queue(service)["request_id"], "run")
    assert result["status"] == "failed"
    assert not service.store.rows("artifacts")


def test_same_request_cannot_be_claimed_twice(service):
    row = queue(service)
    service.execute(row["request_id"], "run-1")
    with pytest.raises(RequestAlreadyClaimed):
        service.execute(row["request_id"], "run-2")


def test_cannot_request_papers_outside_the_query(service):
    query = service.search({"query": "q"})["query"]
    with pytest.raises(ValueError):
        service.submit({"query_id": query["query_id"], "pmids": ["999"]})


def test_failure_sensor_does_not_overwrite_another_run_or_terminal_status(service):
    row = queue(service)
    service.store.claim(row["request_id"], "owner")
    service.fail(row["request_id"], "foreign run failure", "other")
    assert (
        service.one("run_requests", request_id=row["request_id"])["status"] == "running"
    )
    service.fail(row["request_id"], "process died", "owner")
    assert (
        service.one("run_requests", request_id=row["request_id"])["status"] == "failed"
    )
