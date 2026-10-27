"""Primary adapter: FastAPI router exposing the reverse-search domain.

Mounted onto the existing ABI FastAPI app from ``ABIModule.api`` (see
``phases/__init__.py``). Its former page is retired; the HealthyPhases app
(``phases_v2/apps/workspace``) is the project's user interface.
"""

from __future__ import annotations

from fastapi import FastAPI, Query

from phases.app.domain import SearchService
from phases.app.models import PipelinesResponse, SearchResponse

API_PREFIX = "/phases/api"


def register(app: FastAPI, service: SearchService) -> None:
    """Attach the search endpoints to ``app``."""

    @app.get(
        f"{API_PREFIX}/search/semantic",
        response_model=SearchResponse,
        tags=["phases-search"],
        summary="Vector (semantic) reverse search over extracted items",
    )
    def semantic_search(
        q: str = Query(..., description="Natural-language query."),
        k: int = Query(10, ge=1, le=100, description="Number of results."),
        score_threshold: float | None = Query(
            None, description="Optional minimum cosine similarity."
        ),
        pipeline: list[str] | None = Query(
            None, description="Restrict to these extraction pipelines (repeatable)."
        ),
    ) -> SearchResponse:
        hits = service.semantic_search(
            q, k=k, score_threshold=score_threshold, pipelines=pipeline
        )
        return SearchResponse(query=q, mode="semantic", count=len(hits), hits=hits)

    @app.get(
        f"{API_PREFIX}/search/keyword",
        response_model=SearchResponse,
        tags=["phases-search"],
        summary="Keyword (word-presence) reverse search over extracted items",
    )
    def keyword_search(
        q: str = Query(..., description="Words that must all be present."),
        limit: int = Query(25, ge=1, le=100, description="Max results."),
        pipeline: list[str] | None = Query(
            None, description="Restrict to these extraction pipelines (repeatable)."
        ),
    ) -> SearchResponse:
        hits = service.keyword_search(q, limit=limit, pipelines=pipeline)
        return SearchResponse(query=q, mode="keyword", count=len(hits), hits=hits)

    @app.get(
        f"{API_PREFIX}/pipelines",
        response_model=PipelinesResponse,
        tags=["phases-search"],
        summary="List extraction pipelines available as facets",
    )
    def pipelines() -> PipelinesResponse:
        return PipelinesResponse(pipelines=service.list_pipelines())
