"""On-demand enrichment with durable progress and exact identity checks."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from openalex.application.openalex_ports import (
    EnrichmentStore,
    PaperCatalog,
    WorkSource,
)
from openalex.contracts.openalex_validation import validate
from openalex.domain.openalex_errors import (
    AlreadyClaimed,
    EnrichmentNotFound,
    OpenalexUnavailable,
    RequestBudgetExceeded,
)
from openalex.domain.openalex_matching import (
    match,
    normalize_doi,
    normalize_pmid,
    work_id,
)
from openalex.domain.openalex_ownership import owned
from openalex.domain.openalex_work import normalize_work


class OpenalexService:
    def __init__(
        self,
        store: EnrichmentStore,
        catalog: PaperCatalog,
        source: WorkSource,
        batch_size=25,
        request_budget=10000,
        cache_days=7,
        clock=None,
    ):
        self.store, self.catalog, self.source = store, catalog, source
        self.batch_size, self.request_budget, self.cache_days = (
            batch_size,
            request_budget,
            cache_days,
        )
        self.clock = clock or (lambda: datetime.now(UTC))

    def now(self):
        return self.clock().isoformat()

    def create(self, payload):
        command = validate("EnrichQuery", payload)
        query, snapshot, total = self.catalog.capture(command["query_id"])
        row = validate(
            "RequestRecord",
            {
                **command,
                "request_id": str(uuid4()),
                "query": query["query"],
                "source_snapshot": snapshot,
                "total": total,
                "status": "pending",
                "created_at": self.now(),
                "updated_at": self.now(),
                "request_budget": self.request_budget,
            },
        )
        self.store.save("run_requests", [row])
        return row

    def requests(self):
        return sorted(
            self.store.rows("run_requests"), key=lambda r: r["created_at"], reverse=True
        )

    def due(self):
        rows = self.requests()
        return (
            []
            if any(r["status"] == "running" for r in rows)
            else sorted(
                (r for r in rows if r["status"] == "pending"),
                key=lambda r: r["created_at"],
            )[:1]
        )

    def resume(self, request_id):
        UUID(request_id)

        def change(row):
            if row["status"] != "failed":
                raise ValueError("Only interrupted requests can be resumed")
            return {
                **row,
                "status": "pending",
                "generation": row["generation"] + 1,
                "run_id": "",
                "error": "",
                "finished_at": "",
                "budget_used": 0,
                "updated_at": self.now(),
            }

        return self.store.update_request(request_id, change)

    def fail(self, request_id, generation, run_id, message):
        def change(row):
            if (
                row["generation"] != generation
                or row["status"] not in ("pending", "running")
                or (row["run_id"] and row["run_id"] != run_id)
            ):
                raise AlreadyClaimed(request_id)
            return {
                **row,
                "status": "failed",
                "error": message,
                "updated_at": self.now(),
                "finished_at": self.now(),
            }

        try:
            return self.store.update_request(request_id, change)
        except AlreadyClaimed:
            return None

    def execute(self, request_id, generation, run_id):
        def claim(row):
            if row["status"] != "pending" or row["generation"] != generation:
                raise AlreadyClaimed(request_id)
            return {
                **row,
                "status": "running",
                "run_id": run_id,
                "updated_at": self.now(),
            }

        try:
            owner = self.store.update_request(request_id, claim)
        except AlreadyClaimed:
            return None
        paper = None
        try:
            papers = self.catalog.page(
                owner["query_id"],
                owner["source_snapshot"],
                owner["cursor_pmid"],
                self.batch_size,
            )
            for paper in papers:
                previous = self.store.rows(
                    "request_results", request_id=request_id, pmid=paper["pmid"]
                )
                result = previous[0] if previous else self.enrich(paper, owner)

                def progress(row):
                    owned(row, owner)
                    return {
                        **row,
                        "cursor_pmid": paper["pmid"],
                        "processed": row["processed"] + 1,
                        result["status"]: row[result["status"]] + 1,
                        "cached": row["cached"] + int(result["cached"]),
                        "updated_at": self.now(),
                    }

                owner = self.store.update_request(request_id, progress)

            def advance(row):
                owned(row, owner)
                done = row["processed"] >= row["total"]
                if not papers and not done:
                    raise ValueError(
                        "The saved PubMed snapshot is incomplete; inspect its retention settings"
                    )
                return {
                    **row,
                    "status": ("partial" if row["ambiguous"] else "succeeded")
                    if done
                    else "pending",
                    "generation": row["generation"] + 1,
                    "run_id": "",
                    "updated_at": self.now(),
                    "finished_at": self.now() if done else "",
                }

            return self.store.update_request(request_id, advance)
        except AlreadyClaimed:
            return None
        except (OpenalexUnavailable, RequestBudgetExceeded) as exc:
            if paper is not None:
                prior = self.store.rows("paper_enrichments", pmid=paper["pmid"])
                preserved = (
                    prior[0]
                    if prior
                    and prior[0]["input_doi"] == normalize_doi(paper.get("doi"))
                    else {}
                )
                self.store.save_owned(
                    "paper_enrichments",
                    [
                        {
                            **preserved,
                            "pmid": paper["pmid"],
                            "input_doi": normalize_doi(paper.get("doi")),
                            "status": "failed",
                            "checked_at": self.now(),
                            "error": str(exc),
                            "contract_version": 1,
                        }
                    ],
                    owner,
                )
            return self.fail(request_id, generation, run_id, str(exc))
        except Exception:
            # Persist a safe recovery message, then let Dagster retain the traceback.
            self.fail(
                request_id,
                generation,
                run_id,
                "Enrichment interrupted; inspect the Dagster run and resume",
            )
            raise

    def enrich(self, paper, owner):
        prior = self.store.rows("paper_enrichments", pmid=paper["pmid"])
        cached = False
        if prior and not owner["force_refresh"]:
            link = prior[0]
            cached = (
                link["status"] in ("enriched", "no_match", "ambiguous")
                and link["input_doi"] == normalize_doi(paper.get("doi"))
                and datetime.fromisoformat(link["checked_at"])
                > self.clock() - timedelta(days=self.cache_days)
            )
        if not cached:

            def spend():
                def change(row):
                    owned(row, owner)
                    if row["budget_used"] >= row["request_budget"]:
                        raise RequestBudgetExceeded(
                            "HTTP request allowance reached; Resume grants another allowance and preserves progress"
                        )
                    return {
                        **row,
                        "budget_used": row["budget_used"] + 1,
                        "http_attempts": row["http_attempts"] + 1,
                        "updated_at": self.now(),
                    }

                self.store.update_request(owner["request_id"], change)

            identifiers = [f"pmid:{paper['pmid']}"]
            doi = normalize_doi(paper.get("doi"))
            if doi:
                identifiers.append(f"doi:{doi}")
            candidates = [
                c
                for identifier in identifiers
                if (c := self.source.lookup(identifier, spend)) is not None
            ]
            status, raw, reason = match(paper, candidates)
            link = {
                "pmid": paper["pmid"],
                "input_doi": doi,
                "status": status,
                "checked_at": self.now(),
                "error": "" if raw else reason,
                "candidate_ids": sorted({work_id(c["id"]) for c in candidates}),
                "contract_version": 1,
            }
            if raw:
                work = normalize_work(raw, self.now())
                self.store.save_owned("works", [work], owner)
                institutions = [
                    i for a in work["authorships"] for i in a["institutions"]
                ]
                link.update(
                    work_id=work["work_id"],
                    matched_by=reason,
                    enriched_at=self.now(),
                    citation_count=work["citation_count"],
                    topics=[t["name"] for t in work["topics"]],
                    institutions=sorted({i["name"] for i in institutions if i["name"]}),
                    countries=sorted(
                        {i["country_code"] for i in institutions if i["country_code"]}
                    ),
                )
            self.store.save_owned("paper_enrichments", [link], owner)
        result = {
            "request_id": owner["request_id"],
            "pmid": paper["pmid"],
            "status": link["status"],
            "cached": cached,
        }
        self.store.save_owned("request_results", [result], owner)
        return result

    def detail(self, pmid):
        if normalize_pmid(pmid) != pmid:
            raise ValueError("Invalid PMID")
        links = self.store.rows("paper_enrichments", pmid=pmid)
        if not links:
            raise EnrichmentNotFound(pmid)
        link = links[0]
        works = (
            self.store.rows("works", work_id=link["work_id"]) if link["work_id"] else []
        )
        return {"enrichment": link, "work": works[0] if works else None}
