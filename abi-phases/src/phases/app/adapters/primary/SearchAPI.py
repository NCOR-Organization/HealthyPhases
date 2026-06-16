"""Primary adapter: FastAPI router exposing the reverse-search domain.

Mounted onto the existing ABI FastAPI app from ``ABIModule.api`` (see
``phases/__init__.py``). Also serves the static single-page UI at ``/phases/app``.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from phases.app.domain import SearchService
from phases.app.models import PipelinesResponse, SearchResponse

API_PREFIX = "/phases/api"
APP_MOUNT = "/phases/app"

# The canonical UI lives in the Nexus app manifest dir so the platform serves
# it at /app-html/phases/reverse_search/ (embeddable iframe). We also mount it
# at /phases/app for direct / native-dev access, from that same single file.
# this file: app/adapters/primary/SearchAPI.py -> three dirnames up is app/
_APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_FRONTEND_DIR = os.path.join(
    os.path.dirname(_APP_DIR), "apps", "reverse_search"
)


def register(app: FastAPI, service: SearchService) -> None:
    """Attach the search endpoints and the static UI to ``app``."""

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

    if os.path.isdir(_FRONTEND_DIR):
        app.mount(
            APP_MOUNT,
            StaticFiles(directory=_FRONTEND_DIR, html=True),
            name="phases-app",
        )

        @app.get("/phases", include_in_schema=False)
        def _index() -> FileResponse:
            return FileResponse(os.path.join(_FRONTEND_DIR, "index.html"))
