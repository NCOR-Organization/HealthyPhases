"""HTTP endpoints for the reverse-search app.

A thin translation layer, same split as ``PipelineAPI.py``: every decision
lives in :class:`~phases_v2.search.domain.SearchService`, these handlers only
map requests to calls and dataclasses to JSON.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, FastAPI, Query

from phases_v2.search.domain import SearchService

PREFIX = "/phases_v2/api/search"


def build_router(service: SearchService) -> APIRouter:
    router = APIRouter(prefix=PREFIX, tags=["phases_v2-search"])

    @router.get("/semantic")
    def semantic_search(
        q: str = Query(..., description="Natural-language query."),
        k: int = Query(10, ge=1, le=100, description="Number of results."),
        score_threshold: float | None = Query(
            None, description="Optional minimum cosine similarity."
        ),
        prompt: Annotated[
            list[str] | None,
            Query(description="Restrict to these prompts, by name (repeatable)."),
        ] = None,
        model: Annotated[
            list[str] | None, Query(description="Extraction model IDs (repeatable).")
        ] = None,
    ):
        hits = service.semantic_search(
            q, k=k, score_threshold=score_threshold, prompts=prompt, models=model
        )
        return {
            "query": q,
            "mode": "semantic",
            "count": len(hits),
            "hits": [asdict(hit) for hit in hits],
        }

    @router.get("/keyword")
    def keyword_search(
        q: str = Query(..., description="Words that must all be present."),
        limit: int = Query(25, ge=1, le=100, description="Max results."),
        prompt: Annotated[
            list[str] | None,
            Query(description="Restrict to these prompts, by name (repeatable)."),
        ] = None,
        model: Annotated[
            list[str] | None, Query(description="Extraction model IDs (repeatable).")
        ] = None,
    ):
        hits = service.keyword_search(q, limit=limit, prompts=prompt, models=model)
        return {
            "query": q,
            "mode": "keyword",
            "count": len(hits),
            "hits": [asdict(hit) for hit in hits],
        }

    @router.get("/prompts")
    def prompts():
        return {"prompts": service.list_prompts()}

    @router.get("/models")
    def models():
        return {"models": service.list_models()}

    return router


def register(app: FastAPI, service: SearchService) -> None:
    app.include_router(build_router(service))
