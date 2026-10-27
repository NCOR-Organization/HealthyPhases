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
        # Papers come from storage folders or from a collection. A missing input
        # is a 422 naming the field, rather than a 500.
        request = management_call(service.submit_inputs, body)
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
            # str() of a KeyError quotes its message; show the message itself.
            detail = missing.args[0] if missing.args else "Not found."
            raise HTTPException(status_code=404, detail=str(detail)) from missing
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

    @router.get("/sources/pubmed")
    def pubmed_queries():
        return management_call(service.pubmed_queries)

    @router.get("/sources/pubmed/{query_id}")
    def pubmed_artifacts(query_id: str):
        return {"artifacts": management_call(service.pubmed_artifacts, query_id)}

    @router.post(
        "/sources/pubmed/requests",
        status_code=201,
        dependencies=[Depends(require_abi_api_token)],
    )
    def submit_pubmed(body: dict):
        request = management_call(service.submit_pubmed, body)
        return {"request_id": request.request_id, "status": request.status}

    @router.get("/collections")
    def collections(counts: bool = True):
        """Every collection, with how many papers each holds unless ``counts=false``."""
        return {"collections": management_call(service.resources.summaries, counts)}

    @router.get("/collections/{collection_id}")
    def collection(collection_id: str):
        """Members and the papers they resolve to now, each with its status."""
        return management_call(service.resources.detail, collection_id)

    @router.post(
        "/collections", status_code=201, dependencies=[Depends(require_abi_api_token)]
    )
    def create_collection(body: dict):
        return management_call(service.resources.create_collection, body)

    @router.put(
        "/collections/{collection_id}", dependencies=[Depends(require_abi_api_token)]
    )
    def update_collection(collection_id: str, body: dict):
        return management_call(service.resources.update_collection, collection_id, body)

    @router.post(
        "/collections/{collection_id}/members",
        dependencies=[Depends(require_abi_api_token)],
    )
    def add_members(collection_id: str, body: dict):
        return management_call(service.resources.add_members, collection_id, body)

    @router.delete(
        "/collections/{collection_id}/members/{member_id}",
        dependencies=[Depends(require_abi_api_token)],
    )
    def remove_member(collection_id: str, member_id: str):
        return management_call(
            service.resources.remove_member, collection_id, member_id
        )

    @router.post(
        "/collections/{collection_id}/documents",
        status_code=201,
        dependencies=[Depends(require_abi_api_token)],
    )
    async def upload_to_collection(request: Request, collection_id: str, filename: str):
        content = await _read_pdf(request)
        return await run_in_threadpool(
            management_call,
            service.upload_to_collection,
            collection_id,
            filename,
            content,
        )

    @router.delete(
        "/collections/{collection_id}", dependencies=[Depends(require_abi_api_token)]
    )
    def archive_collection(collection_id: str):
        management_call(service.resources.archive_collection, collection_id)
        return {"archived": True}

    @router.post(
        "/prompts", status_code=201, dependencies=[Depends(require_abi_api_token)]
    )
    def save_prompt(body: dict):
        return management_call(service.management.save_prompt, body)

    @router.get("/prompts/versions")
    def prompt_versions(name: str = Query(min_length=1, max_length=100)):
        """Every version of one prompt name, with the runs that used each."""
        return management_call(service.versions.versions, name)

    @router.post("/prompts/try", dependencies=[Depends(require_abi_api_token)])
    def try_prompt(body: dict):
        """Run a draft or version on a few chunks and answer at once. Writes nothing."""
        return management_call(service.try_prompt, body)

    @router.get("/papers")
    def papers(
        q: str = Query(default="", max_length=300),
        chunker_id: str = Query(default="", max_length=200),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        """Ingested papers, searchable by file name or path, with chunk counts.

        One listing for every picker: Collections adds single papers from it,
        Prompts tries a prompt on one of them.
        """
        return management_call(
            service.papers.papers,
            q=q,
            chunker_id=chunker_id,
            limit=limit,
            offset=offset,
        )

    @router.get("/papers/{paper_id}/chunks")
    def paper_chunks(paper_id: str, chunker_id: str = Query(min_length=1)):
        return management_call(service.papers.chunks, paper_id, chunker_id)

    @router.post(
        "/locations", status_code=201, dependencies=[Depends(require_abi_api_token)]
    )
    def create_location(body: dict):
        return management_call(service.management.create_location, body)

    @router.post(
        "/documents", status_code=201, dependencies=[Depends(require_abi_api_token)]
    )
    async def upload_document(request: Request, location: str, filename: str):
        content = await _read_pdf(request)
        return await run_in_threadpool(
            management_call,
            service.management.upload,
            location,
            filename,
            content,
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


async def _read_pdf(request: Request) -> bytes:
    # Raw PDF streaming puts a bound on memory before parsing or storing it.
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="PDFs must not exceed 25 MiB.")
        content.extend(chunk)
    return bytes(content)


def register(app: FastAPI, service: PipelineAppService) -> None:
    app.include_router(build_router(service))
