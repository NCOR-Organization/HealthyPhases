"""Search, request submission and checkpointed artifact publication."""

from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid4

from pubmed.application.pubmed_ports import (
    ArtifactStorage,
    LiteratureSource,
    PublicationStore,
)
from pubmed.contracts.pubmed_validation import validate
from pubmed.domain.pubmed_errors import (
    AcquisitionError,
    FullTextUnavailable,
    PublicationNotFound,
)


def now() -> str:
    return datetime.now(UTC).isoformat()


class PubmedService:
    def __init__(
        self,
        store: PublicationStore,
        source: LiteratureSource,
        storage: ArtifactStorage,
        prefix: str = "pubmed",
    ) -> None:
        self.store, self.source, self.storage = store, source, storage
        self.prefix = prefix.strip("/")
        if not self.prefix or any(p in (".", "..", "") for p in self.prefix.split("/")):
            raise ValueError(
                "datastore_path must be a nonempty relative storage prefix"
            )

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = validate(
            "Search", {"sort": "relevance", "max_results": 100, **payload}
        )
        dates = [
            date.fromisoformat(command[k]) if command[k] else None
            for k in ("start_date", "end_date")
        ]
        if all(dates) and dates[0] > dates[1]:
            raise ValueError("Start date must not be after end date")
        total, papers = self.source.search(command)
        query_id = str(uuid4())
        query = dict(
            command,
            query_id=query_id,
            total=total,
            created_at=now(),
            contract_version=1,
        )
        self.store.save("papers", papers)
        self.store.save(
            "query_papers", [{"query_id": query_id, "pmid": p["pmid"]} for p in papers]
        )
        # Publish the query last, after membership exists.
        self.store.save("queries", [query])
        return {"query": query, "papers": papers, "truncated": total > len(papers)}

    def queries(self) -> list[dict[str, Any]]:
        return sorted(
            self.store.rows("queries"), key=lambda r: r["created_at"], reverse=True
        )

    def browse_papers(self, payload: dict[str, Any]) -> dict[str, Any]:
        filters = validate(
            "BrowsePapers",
            {
                "status": "published",
                "sort": "newest",
                "page": 1,
                "page_size": 50,
                **payload,
            },
        )
        start, end = [
            date.fromisoformat(filters[k]) if filters[k] else None
            for k in ("ingested_from", "ingested_until")
        ]
        if start and end and start > end:
            raise ValueError("Ingested from must not be after ingested until")
        if filters["query_id"]:
            self.one("queries", query_id=filters["query_id"])
        total, rows = self.store.browse_papers(filters)
        artifacts = self.store.rows_for_pmids("artifacts", [p["pmid"] for p in rows])
        by_pmid: dict[str, list[dict]] = {}
        for artifact in artifacts:
            if artifact["status"] == "ready" and artifact["contract_version"] == 1:
                by_pmid.setdefault(artifact["pmid"], []).append(artifact)
        return validate(
            "LibraryPage",
            {
                "papers": [
                    {
                        "last_ingested_at": row["last_ingested_at"],
                        "openalex": {
                            "status": row.get("oa_status") or "not_enriched",
                            "work_id": row.get("oa_work_id") or "",
                            "citation_count": row.get("oa_citation_count") or 0,
                            "topics": row.get("oa_topics") or [],
                            "institutions": row.get("oa_institutions") or [],
                            "enriched_at": row.get("oa_enriched_at") or "",
                        },
                        "paper": {
                            k: v
                            for k, v in row.items()
                            if k != "last_ingested_at" and not k.startswith("oa_")
                        },
                        "artifacts": sorted(
                            by_pmid.get(row["pmid"], []),
                            key=lambda a: (a["published_at"], a["artifact_id"]),
                            reverse=True,
                        ),
                    }
                    for row in rows
                ],
                "total": total,
                "page": filters["page"],
                "page_size": filters["page_size"],
                "total_pages": (total + filters["page_size"] - 1)
                // filters["page_size"],
            },
        )

    def one(self, table: str, **filters: str) -> dict[str, Any]:
        rows = self.store.rows(table, **filters)
        if not rows:
            raise PublicationNotFound(next(iter(filters.values())))
        return rows[0]

    def papers(self, query_id: str) -> list[dict[str, Any]]:
        self.one("queries", query_id=query_id)
        pmids = {r["pmid"] for r in self.store.members(query_id, limit=1000)}
        artifacts = self.store.rows_for_pmids("artifacts", list(pmids))
        return [
            dict(
                p,
                artifacts=[
                    a
                    for a in artifacts
                    if a["pmid"] == p["pmid"] and a["status"] == "ready"
                ],
            )
            for p in self.store.rows_for_pmids("papers", list(pmids))
        ]

    def submit(
        self, payload: dict[str, Any], *, request_id: str | None = None
    ) -> dict[str, Any]:
        command = validate("Submit", payload)
        self.one("queries", query_id=command["query_id"])
        members = {
            r["pmid"]
            for r in self.store.members(
                command["query_id"], pmids=command["pmids"] or None
            )
        }
        if len(members) > 1000:
            raise ValueError(
                "Use full ingestion for queries with more than 1000 papers"
            )
        pmids = command["pmids"] or sorted(members)
        if not pmids or not set(pmids) <= members:
            raise ValueError("Select papers belonging to a nonempty query")
        row = {
            "request_id": request_id or str(uuid4()),
            "query_id": command["query_id"],
            "pmids": pmids,
            "status": "pending",
            "requested_at": now(),
            "started_at": "",
            "finished_at": "",
            "run_id": "",
            "error": "",
            "outcomes": {},
        }
        if request_id is not None:
            return self.store.create_request(row)
        self.store.save("run_requests", [row])
        return row

    def requests(self) -> list[dict[str, Any]]:
        return self.store.recent_requests()

    def retry(self, request_id: str) -> dict[str, Any]:
        row = self.one("run_requests", request_id=request_id)
        if row["status"] not in ("failed", "partial", "succeeded"):
            raise ValueError("Wait for the request to finish before retrying")
        remaining = [
            p
            for p in row["pmids"]
            if row["outcomes"].get(p, {}).get("status") != "ready"
        ]
        if not remaining:
            raise ValueError("All requested papers are already published")
        return self.submit({"query_id": row["query_id"], "pmids": remaining})

    def execute(self, request_id: str, run_id: str) -> dict[str, Any]:
        row = self.store.claim(request_id, run_id)
        try:
            for pmid in row["pmids"]:
                try:
                    artifact = self._publish(pmid)
                    outcome = {
                        "status": "ready",
                        "artifact_id": artifact["artifact_id"],
                    }
                except FullTextUnavailable as exc:
                    outcome = {"status": "unavailable", "error": str(exc)}
                except (AcquisitionError, OSError) as exc:
                    outcome = {"status": "failed", "error": str(exc)}
                row["outcomes"][pmid] = outcome
                self.store.save("run_requests", [row])
            successes = sum(o["status"] == "ready" for o in row["outcomes"].values())
            row["status"] = (
                "succeeded"
                if successes == len(row["pmids"])
                else ("partial" if successes else "failed")
            )
            row["finished_at"] = now()
            self.store.save("run_requests", [row])
            return row
        except Exception:
            # The failure sensor records the error if the process cannot checkpoint.
            self.fail(
                request_id, "Publication interrupted; inspect the Dagster run", run_id
            )
            raise

    def fail(self, request_id: str, error: str, run_id: str) -> None:
        row = self.one("run_requests", request_id=request_id)
        if row["status"] in ("pending", "running") and row.get("run_id", "") in (
            "",
            run_id,
        ):
            row.update(status="failed", error=error, finished_at=now())
            self.store.save("run_requests", [row])

    def _publish(self, pmid: str) -> dict[str, Any]:
        ready = self.store.rows("artifacts", pmid=pmid, status="ready")
        for artifact in ready:
            try:
                content = self.storage.get_object(
                    artifact["storage_prefix"], artifact["storage_key"]
                )
                if sha256(content).hexdigest() == artifact["content_sha256"]:
                    return artifact
            except (FileNotFoundError, OSError):
                pass
        paper = self.one("papers", pmid=pmid)
        if not paper["pmcid"]:
            raise FullTextUnavailable("No PMCID is associated with this PubMed record")
        content, metadata = self.source.download(paper["pmcid"])
        if not content.startswith(b"%PDF-"):
            raise AcquisitionError("The downloaded file is not a PDF")
        digest = sha256(content).hexdigest()
        key = f"{paper['pmcid']}/{digest}.pdf"
        prefix = f"{self.prefix}/papers"
        self.storage.put_object(prefix, key, content)
        artifact = {
            "artifact_id": f"{pmid}:{digest}",
            "pmid": pmid,
            "pmcid": paper["pmcid"],
            "version": metadata["version"],
            "status": "ready",
            "storage_prefix": prefix,
            "storage_key": key,
            "content_sha256": digest,
            "size_bytes": len(content),
            "mime_type": "application/pdf",
            "source_url": metadata["source_url"],
            "license": metadata.get("license", ""),
            "published_at": now(),
            "contract_version": 1,
        }
        self.store.save("artifacts", [artifact])
        return artifact
