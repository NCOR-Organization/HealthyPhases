"""What the assistant can read and do, over the services the app's endpoints use.

Every method is a thin wrapper: the decisions stay in the application services
(collections, runs, prompts, the playground, papers, search, PubMed, OpenAlex),
so the assistant and the app always agree on what is allowed. The wrappers only
shape answers for reading in a conversation: short, plain, and with where to
find the same thing in the app.

Nothing here deletes, archives, removes a member or turns a schedule off.
Queuing work that costs money or time goes through a prepared action and a
token (see :mod:`phases_v2.assistant.confirmations`).
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Iterable
from datetime import date, datetime
from typing import Any

from openalex.domain.openalex_errors import EnrichmentNotFound
from phases_v2.app.app_resources import ResourceNotFound
from phases_v2.assistant.confirmations import (
    ConfirmationGuard,
    RequestContext,
)
from phases_v2.requests.interfaces import RequestNotFound
from pubmed.domain.pubmed_errors import PublicationNotFound

logger = logging.getLogger(__name__)

#: What the services raise for an id that names nothing.
NOT_FOUND = (ResourceNotFound, RequestNotFound, PublicationNotFound, EnrichmentNotFound)

#: A previewed download covers at most this many papers; more is a full ingestion.
PREVIEWED_LIMIT = 1000
#: Rows listed at most per answer; each answer says how many there are in all.
LISTED = 25
#: Results shown per prompt version and model when reading one paper.
ITEMS_PER_GROUP = 15
INTERVALS = {1: "every hour", 24: "every day", 168: "every week"}
#: How findings can be searched, and the search service's name for each.
SEARCH_BY = {"meaning": "semantic", "keyword": "keyword"}

#: What each listing keeps of a row.
VERSION_FIELDS = (
    "prompt_id template output_key first_seen run_count request_count "
    "item_count chunk_count by_model declared"
).split()
DOWNLOAD_FIELDS = "request_id query_id status requested_at finished_at error".split()
FULL_INGESTION_FIELDS = (
    "backfill_id status total discovered completed remaining created_at".split()
)
ENRICHMENT_FIELDS = (
    "request_id query status total processed enriched no_match created_at error"
).split()

RUN = "run"
PUBMED_INGESTION = "pubmed_ingestion"
PUBMED_SCHEDULE = "pubmed_schedule"
OPENALEX_ENRICHMENT = "openalex_enrichment"


class Unavailable(RuntimeError):
    """A part of the workspace this deployment does not have, or cannot reach."""


class Lazy:
    """A service built on its first use, then kept.

    Nexus builds every agent when it starts, and one agent failing to build
    stops the others loading. Building the services only when a tool needs
    them keeps a storage or module failure with the tools that depend on it,
    as an answer the user can read; the next call tries again.
    """

    def __init__(self, name: str, build: Callable[[], Any] | None):
        self._name = name
        self._build = build
        self._value: Any = None

    def get(self) -> Any:
        if self._value is None:
            if self._build is None:
                raise Unavailable(f"{self._name} is unavailable in this deployment.")
            try:
                built = self._build()
            except Unavailable:
                raise
            except Exception as failure:
                logger.exception("Could not build %s for the assistant", self._name)
                raise Unavailable(
                    f"{self._name} could not be reached ({failure}). Try again in "
                    "a moment."
                ) from failure
            if built is None:
                raise Unavailable(f"{self._name} is unavailable in this deployment.")
            self._value = built
        return self._value


class WorkspaceActions:
    def __init__(
        self,
        pipeline: Callable[[], Any],
        *,
        guard: ConfirmationGuard,
        context: Callable[[], RequestContext],
        search: Callable[[], Any] | None = None,
        pubmed: Callable[[], Any] | None = None,
        openalex: Callable[[], Any] | None = None,
    ):
        """Each service is given as a function that builds it on first use:
        ``pipeline`` the app's ``PipelineAppService``, ``search`` the search
        service, and ``pubmed`` and ``openalex`` those modules' services, which
        build ``None`` when the module is not loaded."""
        self._pipeline_service = Lazy("The workspace", pipeline)
        self._search_service = Lazy("Search", search)
        self._pubmed_service = Lazy("PubMed", pubmed)
        self._openalex_service = Lazy("OpenAlex enrichment", openalex)
        self._guard = guard
        self._context = context

    @property
    def _pipeline(self):
        return self._pipeline_service.get()

    # -- collections ------------------------------------------------------

    def list_collections(self) -> dict[str, Any]:
        rows = _ask(self._pipeline.resources.summaries, True)
        return {
            "collections": [
                {
                    "collection_id": c["collection_id"],
                    "name": c["name"],
                    "description": _clip(c.get("description"), 200),
                    "papers": c.get("paper_count"),
                    "members": c["member_count"],
                    "unreadable_members": c.get("failed_members", 0),
                    "updated_at": c["updated_at"],
                }
                for c in rows
            ],
            "where": "Collections",
        }

    def get_collection(self, collection_id: str) -> dict[str, Any]:
        detail = _ask(self._pipeline.resources.detail, collection_id)
        return _plain(
            {
                "collection_id": detail["collection_id"],
                "name": detail["name"],
                "description": detail["description"],
                "members": [
                    {
                        "member_id": m["member_id"],
                        "kind": m["kind"],
                        "label": m.get("label")
                        or m.get("prefix")
                        or m.get("query_id")
                        or m.get("pmid")
                        or m.get("paper_id"),
                        "papers": m.get("paper_count", 0),
                        "error": m.get("error"),
                    }
                    for m in detail["members"]
                ],
                "papers_total": detail["paper_count"],
                "paper_status_counts": detail["status_counts"],
                "unsupported_files": detail.get("unsupported", 0),
                "papers": [
                    {
                        "paper_id": p["paper_id"],
                        "name": p["name"],
                        "pmid": p["pmid"],
                        "status": p["status"],
                        "results": p["results"],
                    }
                    for p in detail["papers"][:LISTED]
                ],
                "papers_listed": min(LISTED, len(detail["papers"])),
                "where": f"Collections → {detail['name']}",
            }
        )

    def create_collection(
        self,
        name: str,
        description: str = "",
        pubmed_search_ids: Iterable[str] = (),
        pmids: Iterable[str] = (),
        paper_ids: Iterable[str] = (),
        folders: Iterable[str] = (),
    ) -> dict[str, Any]:
        created = _ask(
            self._pipeline.resources.create_collection,
            {
                "name": name,
                "description": description or "",
                "members": _members(pubmed_search_ids, pmids, paper_ids, folders),
            },
        )
        return self.get_collection(created["collection_id"])

    def update_collection(
        self,
        collection_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        # Read just before writing, so a change saved meanwhile is kept.
        current = _ask(self._pipeline.resources.collection, collection_id)
        _ask(
            self._pipeline.resources.update_collection,
            collection_id,
            {
                "name": current["name"] if name is None else name,
                "description": current["description"]
                if description is None
                else description,
            },
        )
        return self.get_collection(collection_id)

    def add_to_collection(
        self,
        collection_id: str,
        pubmed_search_ids: Iterable[str] = (),
        pmids: Iterable[str] = (),
        paper_ids: Iterable[str] = (),
        folders: Iterable[str] = (),
    ) -> dict[str, Any]:
        members = _members(pubmed_search_ids, pmids, paper_ids, folders)
        if not members:
            raise ValueError(
                "Name at least one thing to add: a saved PubMed search, a PMID, "
                "a paper id or a storage folder."
            )
        _ask(
            self._pipeline.resources.add_members,
            collection_id,
            {"members": members},
        )
        return self.get_collection(collection_id)

    # -- PubMed ------------------------------------------------------------

    def list_pubmed_searches(self) -> dict[str, Any]:
        listed = _ask(self._pipeline.pubmed_queries)
        queries = listed.get("queries", [])
        return _plain(
            {
                "available": listed.get("available", True),
                "searches": [
                    {
                        "search_id": q["query_id"],
                        "query": q["query"],
                        "created_at": q["created_at"],
                        "matches_in_pubmed": q["total"],
                        "downloaded_papers": q["published_paper_count"],
                        "last_downloaded_at": q.get("last_ingested_at") or None,
                    }
                    for q in queries[:LISTED]
                ],
                "total": len(queries),
                "where": "Library → Search PubMed",
            }
        )

    def get_pubmed_search(self, search_id: str) -> dict[str, Any]:
        """A saved search with the papers it previewed and which are downloaded."""
        pubmed = self._pubmed_service.get()
        query = _ask(pubmed.one, "queries", query_id=search_id)
        papers = _ask(pubmed.papers, search_id)
        return _plain(
            {
                "search_id": search_id,
                "query": query["query"],
                "matches_in_pubmed": query["total"],
                "previewed": len(papers),
                "downloaded": sum(1 for p in papers if p.get("artifacts")),
                "papers": [_pubmed_paper(p) for p in papers[:LISTED]],
                "where": "Library → Search PubMed",
            }
        )

    def search_pubmed(
        self,
        query: str,
        max_results: int = 100,
        start_date: str = "",
        end_date: str = "",
        sort: str = "relevance",
    ) -> dict[str, Any]:
        """Search PubMed. Saves the search; downloads nothing."""
        pubmed = self._pubmed_service.get()
        found = _ask(
            pubmed.search,
            {
                "query": query,
                "max_results": max_results,
                "start_date": start_date or "",
                "end_date": end_date or "",
                "sort": sort or "relevance",
            },
        )
        saved = found["query"]
        return _plain(
            {
                "search_id": saved["query_id"],
                "query": saved["query"],
                "matches_in_pubmed": saved["total"],
                "previewed": len(found["papers"]),
                "papers": [_pubmed_paper(p) for p in found["papers"][:LISTED]],
                "where": "Library → Search PubMed",
            }
        )

    def browse_library(
        self, search: str = "", search_id: str = "", page: int = 1
    ) -> dict[str, Any]:
        """Downloaded PubMed papers, newest first, one page at a time."""
        pubmed = self._pubmed_service.get()
        found = _ask(
            pubmed.browse_papers,
            {
                "search": search or "",
                "query_id": search_id or "",
                "page": max(1, page),
                "page_size": LISTED,
            },
        )
        return _plain(
            {
                "papers": [
                    dict(
                        _pubmed_paper(row["paper"]),
                        downloaded=bool(row["artifacts"]),
                        last_downloaded_at=row["last_ingested_at"] or None,
                        citations=row["openalex"]["citation_count"],
                    )
                    for row in found["papers"]
                ],
                "total": found["total"],
                "page": found["page"],
                "pages": found["total_pages"],
                "where": "Library → Papers",
            }
        )

    # -- prompts, models, chunkers ------------------------------------------

    def list_prompts(self) -> dict[str, Any]:
        prompts = self._pipeline.prompts()
        return {
            "prompts": [
                {
                    "prompt_id": p["prompt_id"],
                    "name": p["name"],
                    "output_format": p["output_key"],
                    "text_start": _clip(p["template"], 160),
                }
                for p in prompts
            ],
            "where": "Prompts",
        }

    def get_prompt_versions(self, name: str) -> dict[str, Any]:
        found = _ask(self._pipeline.versions.versions, name)
        return _plain(
            {
                "name": found["name"],
                "versions": [
                    _pick(version, VERSION_FIELDS) for version in found["versions"]
                ],
                "where": f"Prompts → {found['name']} → Versions",
            }
        )

    def save_prompt_version(
        self, name: str, template: str, output_format: str
    ) -> dict[str, Any]:
        known = {p["prompt_id"] for p in self._pipeline.prompts()}
        saved = _ask(
            self._pipeline.management.save_prompt,
            {"name": name, "template": template, "output_key": output_format},
        )
        return {
            "prompt_id": saved["prompt_id"],
            "name": saved["name"],
            "output_format": saved["output_key"],
            "already_saved": saved["prompt_id"] in known,
            "where": f"Prompts → {saved['name']}",
        }

    def list_models_and_chunkers(self) -> dict[str, Any]:
        return {
            "models": [
                {
                    "model_id": m["model_id"],
                    "name": m["display_name"],
                    "available": m["available"],
                }
                for m in self._pipeline.models()
            ],
            "chunkers": self._pipeline.chunkers(),
        }

    def try_prompt(
        self,
        paper_id: str,
        model_id: str,
        chunker_id: str,
        prompt_id: str = "",
        name: str = "",
        template: str = "",
        output_format: str = "",
        chunk_seqs: Iterable[int] = (),
        first: int = 3,
        compare_with_prompt_id: str = "",
    ) -> dict[str, Any]:
        """Run a saved version or a draft on a few chunks of one paper. Saves nothing."""
        payload: dict[str, Any] = {
            "model_id": model_id,
            "paper_id": paper_id,
            "chunker_id": chunker_id,
        }
        if prompt_id and template:
            raise ValueError(
                "Try one thing at a time: either a saved prompt version or a draft."
            )
        if prompt_id:
            payload["prompt_id"] = prompt_id
        elif not template:
            raise ValueError(
                "Give a saved prompt version's prompt_id, or a draft template to try."
            )
        else:
            payload["draft"] = {
                "name": name or "Draft",
                "template": template,
                "output_key": output_format or "results",
            }
        seqs = [int(seq) for seq in chunk_seqs]
        if seqs:
            payload["seqs"] = seqs
        else:
            payload["first"] = first
        if compare_with_prompt_id:
            payload["baseline_prompt_id"] = compare_with_prompt_id
        report = _ask(self._pipeline.try_prompt, payload)
        return _plain(
            {
                "prompt_id": report["prompt_id"],
                "name": report["name"],
                "output_format": report["output_key"],
                "model_id": report["model_id"],
                "compared_with": report["baseline_prompt_id"],
                "timed_out": report["timed_out"],
                "seconds": round(report["elapsed_ms"] / 1000, 1),
                "chunks": [
                    {
                        "seq": chunk["seq"],
                        "text_start": _clip(chunk["text"], 300),
                        "status": chunk["status"],
                        "items": chunk["items"],
                        "error": chunk["error"],
                        "earlier": chunk["baseline"],
                    }
                    for chunk in report["chunks"]
                ],
                "saved": False,
                "where": "Prompts → <prompt> → Try it",
            }
        )

    # -- papers and results -------------------------------------------------

    def list_papers(
        self,
        q: str = "",
        collection_id: str = "",
        run_id: str = "",
        has_results: bool | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {
            "q": q or "",
            "collection": collection_id or "",
            "request_id": run_id or "",
            "sort": "title",
            "limit": LISTED,
            "offset": max(0, offset),
        }
        if has_results is not None:
            query["has_results"] = has_results
        page = _ask(self._pipeline.paper_list, query)
        return _plain(
            {
                "papers": [
                    {
                        "paper_id": p["paper_id"],
                        "title": p["title"],
                        "pmid": p.get("pmid"),
                        "source": p.get("source"),
                        "chunks": p.get("chunks"),
                        "results": p.get("item_count", 0),
                        "results_by_prompt": p.get("items"),
                    }
                    for p in page["papers"]
                ],
                "total": page.get("total"),
                "offset": query["offset"],
                "where": "Results",
            }
        )

    def get_paper_results(
        self, paper_id: str, prompt_id: str = "", model_id: str = ""
    ) -> dict[str, Any]:
        """A paper, what ran on it, and its results by prompt version and model."""
        found = _ask(self._pipeline.paper_results.paper, paper_id)
        paper = found["paper"]
        groups = [
            g
            for g in found["results"]
            if (not prompt_id or g["prompt_id"] == prompt_id)
            and (not model_id or (g["model_id"] or "") == model_id)
        ]
        pubmed = found.get("pubmed") or {}
        return _plain(
            {
                "paper_id": paper_id,
                "title": paper.get("title"),
                "pmid": paper.get("pmid"),
                "journal": pubmed.get("journal"),
                "published": pubmed.get("publication_date"),
                "chunkers": found["chunkers"],
                "ran": found["ran"],
                "runs": [
                    {"run_id": r.get("request_id"), "status": r.get("status")}
                    for r in found["requests"][:LISTED]
                ],
                "results": [
                    {
                        "prompt_id": g["prompt_id"],
                        "prompt_name": g["prompt_name"],
                        "model_id": g["model_id"],
                        "succeeded_chunks": g["succeeded"],
                        "failed_chunks": g["failed"],
                        "item_count": g["item_count"],
                        "items": [
                            {
                                "chunk_seq": item["chunk_seq"],
                                "text": item["text"],
                                "relations": item["relations"][:3],
                            }
                            for item in g["items"][:ITEMS_PER_GROUP]
                        ],
                        "failures": [
                            {"seq": f["seq"], "error": f["error"]}
                            for f in g["failures"][:3]
                        ],
                    }
                    for g in groups
                ],
                "where": f"Results → {paper.get('title') or paper_id}",
            }
        )

    def get_paper_chunks(
        self, paper_id: str, chunker_id: str, page: int = 1
    ) -> dict[str, Any]:
        """A paper's chunks for one chunker, in order, one page at a time."""
        found = _ask(self._pipeline.papers.chunks, paper_id, chunker_id)
        chunks = found["chunks"]
        pages = max(1, -(-len(chunks) // LISTED))
        page = min(max(1, page), pages)
        start = (page - 1) * LISTED
        return _plain(
            dict(
                found,
                chunks=chunks[start : start + LISTED],
                total=len(chunks),
                page=page,
                pages=pages,
            )
        )

    def search_findings(
        self,
        query: str,
        by: str = "meaning",
        collection_id: str = "",
        prompt_names: Iterable[str] = (),
        model_ids: Iterable[str] = (),
        limit: int = 10,
    ) -> dict[str, Any]:
        """Extracted findings by meaning or by keyword, optionally in one collection."""
        if by not in SEARCH_BY:
            raise ValueError("Search findings by 'meaning' or by 'keyword'.")
        options: dict[str, Any] = {
            "prompts": list(prompt_names) or None,
            "models": list(model_ids) or None,
        }
        if collection_id:
            options["papers"] = _ask(self._pipeline.resources.paper_ids, collection_id)
        scoped, _snapshot = self._search_service.get().read_view(None)
        hits, total = scoped.page(
            SEARCH_BY[by],
            query=query,
            limit=max(1, min(limit, LISTED)),
            offset=0,
            **options,
        )
        return _plain(
            {
                "hits": [
                    {
                        "finding": h.extracted_text,
                        "paper_id": h.paper_id,
                        "paper": h.paper_name,
                        "prompt": h.prompt_name,
                        "model_id": h.model_id,
                        "chunk_seq": h.chunk_seq,
                        "score": h.score,
                    }
                    for h in hits
                ],
                "total": total,
                "where": "Search",
            }
        )

    # -- runs and saved configurations --------------------------------------

    def list_runs(self) -> dict[str, Any]:
        return _plain(
            {
                "runs": [_run(r) for r in _ask(self._pipeline.recent_requests, LISTED)],
                "where": "Runs",
            }
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        found = _ask(self._pipeline.request, run_id)
        return _plain(dict(_run(found), counts=found.get("counts")))

    def list_downloads_and_enrichments(self) -> dict[str, Any]:
        """PubMed downloads, full ingestions, schedules and OpenAlex enrichments."""
        out: dict[str, Any] = {"unavailable": []}
        try:
            pubmed = self._pubmed_service.get()
        except Unavailable as missing:
            out["unavailable"].append(str(missing))
        else:
            from pubmed.application.pubmed_backfills import PubmedBackfills
            from pubmed.application.pubmed_schedules import PubmedSchedules

            out["downloads"] = [
                dict(_pick(r, DOWNLOAD_FIELDS), papers=len(r.get("pmids") or []))
                for r in pubmed.requests()[:10]
            ]
            out["full_ingestions"] = [
                _pick(b, FULL_INGESTION_FIELDS)
                for b in PubmedBackfills(pubmed).list()[:10]
            ]
            out["schedules"] = [
                {
                    "schedule_id": s["schedule_id"],
                    "name": s["name"],
                    "query": s["search"]["query"],
                    "how_often": INTERVALS.get(s["interval_hours"]),
                    "enabled": s["enabled"],
                    "downloads_new_papers": s["ingest_new"],
                    "next_run_at": s.get("next_run_at"),
                    "status": s.get("status"),
                }
                for s in PubmedSchedules(pubmed).list()
            ]
        try:
            openalex = self._openalex_service.get()
        except Unavailable as missing:
            out["unavailable"].append(str(missing))
        else:
            out["enrichments"] = [
                _pick(r, ENRICHMENT_FIELDS) for r in openalex.requests()[:10]
            ]
        out["where"] = (
            "Library → Downloads, Library → Schedules and Library → Enrichment"
        )
        return _plain(out)

    def list_run_configurations(self) -> dict[str, Any]:
        rows = _ask(self._pipeline.management.pipelines)
        return _plain(
            {
                "configurations": [
                    {
                        "configuration_id": r["pipeline_id"],
                        "name": r["name"],
                        "inputs": r["inputs"],
                        "created_at": r["created_at"],
                    }
                    for r in rows[:LISTED]
                ],
                "where": "Runs → New run → Saved configurations",
            }
        )

    def save_run_configuration(
        self,
        name: str,
        collection_id: str,
        chunker_id: str,
        prompt_ids: Iterable[str],
        model_id: str,
    ) -> dict[str, Any]:
        """Save a run's choices to reuse later. Queues nothing."""
        saved = _ask(
            self._pipeline.management.save_pipeline,
            {
                "name": name,
                "inputs": {
                    "locations": [],
                    "collection_id": collection_id,
                    "chunker_id": chunker_id,
                    "prompt_ids": list(prompt_ids),
                    "model_id": model_id,
                },
            },
        )
        return _plain(
            {
                "configuration_id": saved["pipeline_id"],
                "name": saved["name"],
                "queued": False,
                "where": "Runs → New run → Saved configurations",
            }
        )

    # -- costly: a pipeline run ---------------------------------------------

    def prepare_run(
        self,
        collection_id: str,
        chunker_id: str,
        prompt_ids: Iterable[str],
        model_id: str,
    ) -> dict[str, Any]:
        params = _run_params(collection_id, chunker_id, prompt_ids, model_id)
        # The same checks queuing makes, so a yes is never asked for a run
        # that would be refused.
        _ask(self._pipeline.management.validate_inputs, dict(params, locations=[]))
        # One resolution for the summary and the token, so the user agrees to
        # exactly the papers the token is bound to.
        collection, scope = _ask(self._pipeline.collection_run_scope, collection_id)
        counts = _ask(self._pipeline.resources.status_counts, scope)
        prompts = {p["prompt_id"]: p for p in self._pipeline.prompts()}
        models = {m["model_id"]: m for m in self._pipeline.models()}
        chunkers = {c["chunker_id"]: c for c in self._pipeline.chunkers()}
        lines = [
            f"Queue a pipeline run on the collection “{collection['name']}”: "
            f"{_count(len(scope.papers), 'paper')} "
            f"({counts['results']} already with results, "
            f"{counts['ingested']} ingested without results, "
            f"{counts['not_ingested']} still to ingest).",
            "Prompts: "
            + "; ".join(
                f"{prompts[p]['name']} (version {p[-8:]}, {prompts[p]['output_key']})"
                for p in params["prompt_ids"]
            )
            + ".",
            f"Model: {models[model_id]['display_name']} ({model_id}).",
            f"Chunker: {chunkers[chunker_id]['name']} ({chunker_id}).",
        ]
        warning = self._pipeline.chunker_warning(chunker_id)
        if warning:
            lines.append(warning)
        lines.append(
            "It calls the model on every chunk not yet extracted with these "
            "prompts, in the background. Follow it in Runs."
        )
        return self._prepared(
            RUN,
            params,
            "\n".join(lines),
            basis=scope.manifest(),
            papers=len(scope.papers),
        )

    def queue_run(
        self,
        token: str,
        collection_id: str,
        chunker_id: str,
        prompt_ids: Iterable[str],
        model_id: str,
    ) -> dict[str, Any]:
        params = _run_params(collection_id, chunker_id, prompt_ids, model_id)
        context = self._context()
        _collection, scope = _ask(self._pipeline.collection_run_scope, collection_id)
        self._guard.redeem(token, RUN, params, context, basis=scope.manifest())
        # Submitted with the resolution just checked: the run reads exactly the
        # papers the user agreed to, not ones that joined a moment later.
        request = _ask(
            self._pipeline.submit_collection_run,
            **params,
            requested_by=context.user[:200] or None,
            resolution=scope,
        )
        return {
            "queued": True,
            "run_id": request.request_id,
            "status": request.status,
            "where": f"Runs → {request.request_id}",
        }

    # -- costly: PubMed downloads, schedules, OpenAlex -----------------------

    def prepare_pubmed_ingestion(
        self, search_id: str, which: str = "previewed", pmids: Iterable[str] = ()
    ) -> dict[str, Any]:
        """``previewed``: the search's previewed papers (or ``pmids`` among them);
        ``all``: every paper PubMed matches, found and downloaded in batches."""
        pubmed = self._pubmed_service.get()
        params = _ingestion_params(search_id, which, pmids)
        query = _ask(pubmed.one, "queries", query_id=search_id)
        if which == "all":
            summary = (
                f"Find and download every paper PubMed matches for “{query['query']}”: "
                f"about {_count(query['total'], 'paper')}, in batches, until all are "
                "downloaded. Follow it in Library → Downloads."
            )
            return self._prepared(
                PUBMED_INGESTION, params, summary, papers=query["total"]
            )
        chosen, downloaded = self._previewed_choice(pubmed, params)
        summary = (
            f"Download the full text of {_count(len(chosen), 'paper')} from the saved "
            f"PubMed search “{query['query']}”"
            + (f" ({downloaded} of them downloaded before)" if downloaded else "")
            + ". Follow it in Library → Downloads."
        )
        return self._prepared(
            PUBMED_INGESTION, params, summary, basis=chosen, papers=len(chosen)
        )

    def queue_pubmed_ingestion(
        self,
        token: str,
        search_id: str,
        which: str = "previewed",
        pmids: Iterable[str] = (),
    ) -> dict[str, Any]:
        pubmed = self._pubmed_service.get()
        params = _ingestion_params(search_id, which, pmids)
        if which == "all":
            self._guard.redeem(token, PUBMED_INGESTION, params, self._context())
            from pubmed.application.pubmed_backfills import PubmedBackfills

            row = _ask(PubmedBackfills(pubmed).create, {"query_id": search_id})
            return _plain(
                {
                    "queued": True,
                    "full_ingestion_id": row["backfill_id"],
                    "status": row["status"],
                    "where": "Library → Downloads",
                }
            )
        chosen, _downloaded = self._previewed_choice(pubmed, params)
        self._guard.redeem(
            token, PUBMED_INGESTION, params, self._context(), basis=chosen
        )
        # The PMIDs the summary counted, named: an empty list would mean every
        # member of the search, including any that joined since.
        row = _ask(pubmed.submit, {"query_id": search_id, "pmids": chosen})
        return {
            "queued": True,
            "download_id": row["request_id"],
            "papers": len(row["pmids"]),
            "status": row["status"],
            "where": "Library → Downloads",
        }

    def _previewed_choice(
        self, pubmed, params: dict[str, Any]
    ) -> tuple[list[str], int]:
        """The PMIDs a previewed download fetches, and how many were downloaded before."""
        search_id = params["search_id"]
        # The publisher's own limit, checked before asking rather than after.
        if pubmed.store.member_count(search_id) > PREVIEWED_LIMIT:
            raise ValueError(
                f"This search has more than {PREVIEWED_LIMIT} papers; download all "
                "of them with which='all' instead."
            )
        previewed = {p["pmid"]: p for p in _ask(pubmed.papers, search_id)}
        chosen = params["pmids"] or sorted(previewed)
        outside = [p for p in chosen if p not in previewed]
        if outside:
            raise ValueError(
                "These PMIDs are not among the search's previewed papers: "
                + ", ".join(outside[:10])
            )
        if not chosen:
            raise ValueError("This search previewed no papers to download.")
        downloaded = sum(1 for p in chosen if previewed[p].get("artifacts"))
        return chosen, downloaded

    def prepare_pubmed_schedule(
        self,
        search_id: str,
        name: str,
        interval_hours: int = 24,
        download_new_papers: bool = True,
    ) -> dict[str, Any]:
        pubmed = self._pubmed_service.get()
        params = _schedule_params(search_id, name, interval_hours, download_new_papers)
        query = _ask(pubmed.one, "queries", query_id=search_id)
        summary = (
            f"Create the schedule “{params['name']}”: search PubMed for "
            f"“{query['query']}” {INTERVALS[interval_hours]}"
            + (
                ", and download the new papers it finds each time."
                if download_new_papers
                else ", saving what it finds without downloading."
            )
            + " See it in Library → Schedules."
        )
        # A saved search never changes, so the parameters are the whole scope.
        return self._prepared(PUBMED_SCHEDULE, params, summary)

    def create_pubmed_schedule(
        self,
        token: str,
        search_id: str,
        name: str,
        interval_hours: int = 24,
        download_new_papers: bool = True,
    ) -> dict[str, Any]:
        pubmed = self._pubmed_service.get()
        params = _schedule_params(search_id, name, interval_hours, download_new_papers)
        self._guard.redeem(token, PUBMED_SCHEDULE, params, self._context())
        from pubmed.application.pubmed_schedules import PubmedSchedules

        row = _ask(
            PubmedSchedules(pubmed).create,
            {
                "query_id": search_id,
                "name": params["name"],
                "interval_hours": interval_hours,
                "enabled": True,
                "ingest_new": download_new_papers,
            },
        )
        return {
            "created": True,
            "schedule_id": row["schedule_id"],
            "next_run_at": row["next_run_at"],
            "where": "Library → Schedules",
        }

    def prepare_openalex_enrichment(
        self, search_id: str, refresh: bool = False
    ) -> dict[str, Any]:
        openalex = self._openalex_service.get()
        params = {"search_id": search_id, "refresh": bool(refresh)}
        query, _snapshot, total = _ask(openalex.catalog.capture, search_id)
        summary = (
            f"Enrich {_count(total, 'paper')} of the saved PubMed search "
            f"“{query['query']}” with OpenAlex: citations, topics and institutions"
            + (
                ", fetching again even papers enriched recently."
                if refresh
                else "; papers enriched recently are kept as they are."
            )
            + " Follow it in Library → Enrichment."
        )
        return self._prepared(
            OPENALEX_ENRICHMENT, params, summary, basis=total, papers=total
        )

    def queue_openalex_enrichment(
        self, token: str, search_id: str, refresh: bool = False
    ) -> dict[str, Any]:
        openalex = self._openalex_service.get()
        params = {"search_id": search_id, "refresh": bool(refresh)}
        _query, _snapshot, total = _ask(openalex.catalog.capture, search_id)
        self._guard.redeem(
            token, OPENALEX_ENRICHMENT, params, self._context(), basis=total
        )
        row = _ask(
            openalex.create, {"query_id": search_id, "force_refresh": bool(refresh)}
        )
        return {
            "queued": True,
            "enrichment_id": row["request_id"],
            "papers": row["total"],
            "status": row["status"],
            "where": "Library → Enrichment",
        }

    # -- helpers ------------------------------------------------------------

    def _prepared(
        self,
        action: str,
        params: dict[str, Any],
        summary: str,
        basis: Any = "",
        **facts: Any,
    ) -> dict[str, Any]:
        confirmation = self._guard.issue(action, params, self._context(), basis)
        return {
            "summary": summary,
            **facts,
            "confirmation_token": confirmation.token,
            "expires_in_minutes": confirmation.expires_in_minutes,
            "next": (
                "Show the user this summary and ask whether to go ahead. Only "
                "after they say yes in their next message, call the matching "
                "queue or create tool with this token and exactly these parameters."
            ),
        }


def _ask(action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call a service, saying "not found" in its own words rather than as a key.

    Only the services' own not-found errors: any other ``KeyError`` is a fault,
    and reading it as a wrong id would hide it.
    """
    try:
        return action(*args, **kwargs)
    except NOT_FOUND as missing:
        detail = str(missing.args[0]) if missing.args else ""
        # Some services raise with the id alone; say what that means.
        if not detail or detail in {str(v) for v in (*args, *kwargs.values())}:
            detail = (
                f"Nothing was found with the id {detail}. List them first to "
                "check the id."
                if detail
                else "Nothing was found with that id."
            )
        raise LookupError(detail) from missing


def _members(
    pubmed_search_ids: Iterable[str],
    pmids: Iterable[str],
    paper_ids: Iterable[str],
    folders: Iterable[str],
) -> list[dict[str, Any]]:
    return [
        *({"pubmed_query": {"query_id": q}} for q in pubmed_search_ids),
        *({"paper": {"pmid": str(p)}} for p in pmids),
        *({"paper": {"paper_id": p}} for p in paper_ids),
        *({"folder": {"prefix": f}} for f in folders),
    ]


def _run_params(
    collection_id: str, chunker_id: str, prompt_ids: Iterable[str], model_id: str
) -> dict[str, Any]:
    return {
        "collection_id": collection_id,
        "chunker_id": chunker_id,
        # Order does not change what a run does, so it does not change the yes.
        "prompt_ids": sorted(set(prompt_ids)),
        "model_id": model_id,
    }


def _ingestion_params(
    search_id: str, which: str, pmids: Iterable[str]
) -> dict[str, Any]:
    if which not in ("previewed", "all"):
        raise ValueError("which must be 'previewed' or 'all'.")
    chosen = sorted({str(p) for p in pmids})
    if which == "all" and chosen:
        raise ValueError("Give PMIDs only when downloading previewed papers.")
    return {"search_id": search_id, "which": which, "pmids": chosen}


def _schedule_params(
    search_id: str, name: str, interval_hours: int, download_new_papers: bool
) -> dict[str, Any]:
    if interval_hours not in INTERVALS:
        raise ValueError(
            "interval_hours must be 1 (hourly), 24 (daily) or 168 (weekly)."
        )
    if not (name or "").strip():
        raise ValueError("Give the schedule a name.")
    return {
        "search_id": search_id,
        "name": name.strip(),
        "interval_hours": interval_hours,
        "download_new_papers": bool(download_new_papers),
    }


def _run(request: dict[str, Any]) -> dict[str, Any]:
    collection = request.get("collection") or {}
    return {
        "run_id": request["request_id"],
        "status": request["status"],
        "collection": collection.get("name"),
        "folders": [
            loc
            for loc in request.get("locations", [])
            if not loc.startswith("dataset:")
        ],
        "prompt_ids": request.get("prompt_ids"),
        "model_id": request.get("model_id"),
        "chunker_id": request.get("chunker_id"),
        "requested_at": request.get("requested_at"),
        "started_at": request.get("started_at"),
        "finished_at": request.get("finished_at"),
        "requested_by": request.get("requested_by"),
        "error": request.get("error"),
    }


def _pubmed_paper(paper: dict[str, Any]) -> dict[str, Any]:
    out = {
        "pmid": paper.get("pmid"),
        "title": paper.get("title"),
        "journal": paper.get("journal") or None,
        "published": paper.get("publication_date") or None,
    }
    if "artifacts" in paper:
        out["downloaded"] = bool(paper["artifacts"])
    return out


def _pick(row: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    return {field: row[field] for field in fields if field in row}


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _clip(text: str | None, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _plain(value: Any) -> Any:
    """Only what JSON can carry, so every answer reads the same to the assistant."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_plain(v) for v in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value
