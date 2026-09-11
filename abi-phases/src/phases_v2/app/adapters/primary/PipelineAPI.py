"""HTTP endpoints for the pipeline app.

A thin translation layer: every decision lives in
:class:`~phases_v2.app.service.PipelineAppService`, so these handlers only map
requests to calls and errors to status codes.

Nothing here contacts the orchestrator. Submitting records a row; a Dagster
sensor picks it up.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from naas_abi_core.apps.api.abi_api_key_auth import require_abi_api_token
from starlette.concurrency import run_in_threadpool

from phases_v2.app.contracts.pipeline_validation import validate_message
from phases_v2.app.pipeline_management import MAX_UPLOAD_BYTES, ManagementUnavailable
from phases_v2.app.service import PipelineAppService
from phases_v2.requests.interfaces import RequestNotFound

PREFIX = "/phases_v2/api"


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
    def documents(
        location: list[str] = Query(default=[]),
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        """Preview what a run over these locations would ingest."""
        try:
            for prefix in location:
                service.management.location(prefix)
            return service.documents(location, limit=limit)
        except ValueError as invalid:
            raise HTTPException(status_code=422, detail=str(invalid)) from invalid

    @router.get("/chunker-warning")
    def chunker_warning(chunker_id: str = ""):
        return {"warning": service.chunker_warning(chunker_id)}

    @router.post(
        "/requests", status_code=201, dependencies=[Depends(require_abi_api_token)]
    )
    def submit(body: dict):
        try:
            validate_message("PipelineInputs", body)
            request = service.submit_run(
                locations=body.get("locations", []),
                chunker_id=body.get("chunker_id", ""),
                prompt_ids=body.get("prompt_ids", []),
                model_id=body.get("model_id", ""),
                requested_by=body.get("requested_by"),
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

    def management_call(operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except ValueError as invalid:
            raise HTTPException(status_code=422, detail=str(invalid)) from invalid
        except KeyError as missing:
            raise HTTPException(status_code=404, detail=str(missing)) from missing
        except ManagementUnavailable as unavailable:
            raise HTTPException(
                status_code=503, detail=str(unavailable)
            ) from unavailable

        except Exception as failure:
            logging.getLogger(__name__).exception(
                "Pipeline management operation failed"
            )
            raise HTTPException(
                status_code=503, detail="Storage operation failed. Please retry."
            ) from failure

    @router.post(
        "/prompts", status_code=201, dependencies=[Depends(require_abi_api_token)]
    )
    def save_prompt(body: dict):
        return management_call(service.management.save_prompt, body)

    @router.post(
        "/locations", status_code=201, dependencies=[Depends(require_abi_api_token)]
    )
    def create_location(body: dict):
        return management_call(service.management.create_location, body)

    @router.post(
        "/documents", status_code=201, dependencies=[Depends(require_abi_api_token)]
    )
    async def upload_document(request: Request, location: str, filename: str):
        # Raw PDF streaming puts a bound on memory before parsing or storing it.
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413, detail="PDFs must not exceed 25 MiB."
                )
            content.extend(chunk)
        return await run_in_threadpool(
            management_call,
            service.management.upload,
            location,
            filename,
            bytes(content),
        )

    @router.get("/pipelines")
    def pipelines():
        return {"pipelines": management_call(service.management.pipelines)}

    @router.post(
        "/pipelines", status_code=201, dependencies=[Depends(require_abi_api_token)]
    )
    def save_pipeline(body: dict):
        return management_call(service.management.save_pipeline, body)

    @router.post(
        "/pipelines/{pipeline_id}/requests",
        status_code=201,
        dependencies=[Depends(require_abi_api_token)],
    )
    def run_pipeline(pipeline_id: str):
        pipeline = management_call(service.management.pipeline, pipeline_id)
        return submit(pipeline["inputs"])

    return router


def register(app: FastAPI, service: PipelineAppService) -> None:
    app.include_router(build_router(service))
