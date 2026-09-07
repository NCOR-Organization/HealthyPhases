"""HTTP endpoints for the pipeline app.

A thin translation layer: every decision lives in
:class:`~phases_v2.app.service.PipelineAppService`, so these handlers only map
requests to calls and errors to status codes.

Nothing here contacts the orchestrator. Submitting records a row; a Dagster
sensor picks it up.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException, Query
from pydantic import BaseModel

from phases_v2.app.service import PipelineAppService
from phases_v2.requests.interfaces import RequestNotFound

PREFIX = "/phases_v2/api"


class SubmitRun(BaseModel):
    locations: list[str] = []
    chunker_id: str = ""
    prompt_ids: list[str] = []
    model_id: str = ""
    requested_by: str | None = None


def build_router(service: PipelineAppService) -> APIRouter:
    router = APIRouter(prefix=PREFIX, tags=["phases_v2"])

    @router.get("/prompts")
    def prompts():
        return {"prompts": service.prompts()}

    @router.get("/models")
    def models():
        return {"models": service.models()}

    @router.get("/chunkers")
    def chunkers():
        return {"chunkers": service.chunkers()}

    @router.get("/locations")
    def locations():
        return {"locations": service.locations()}

    @router.get("/documents")
    def documents(location: list[str] = Query(default=[]), limit: int = 200):
        """Preview what a run over these locations would ingest."""
        return service.documents(location, limit=limit)

    @router.get("/chunker-warning")
    def chunker_warning(chunker_id: str = ""):
        return {"warning": service.chunker_warning(chunker_id)}

    @router.post("/requests", status_code=201)
    def submit(body: SubmitRun):
        try:
            request = service.submit_run(
                locations=body.locations,
                chunker_id=body.chunker_id,
                prompt_ids=body.prompt_ids,
                model_id=body.model_id,
                requested_by=body.requested_by,
            )
        except ValueError as invalid:
            # The user left something out — say which, rather than 500.
            raise HTTPException(status_code=422, detail=str(invalid)) from invalid
        return {"request_id": request.request_id, "status": request.status}

    @router.get("/requests")
    def recent(limit: int = 25):
        return {"requests": service.recent_requests(limit)}

    @router.get("/requests/{request_id}")
    def one(request_id: str):
        try:
            return service.request(request_id)
        except RequestNotFound as missing:
            raise HTTPException(status_code=404, detail=str(missing)) from missing

    return router


def register(app: FastAPI, service: PipelineAppService) -> None:
    app.include_router(build_router(service))
