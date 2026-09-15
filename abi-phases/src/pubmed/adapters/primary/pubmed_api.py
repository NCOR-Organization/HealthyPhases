"""HTTP mapping for the Nexus app. Downloads run only in the worker."""

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException

from pubmed.domain.pubmed_errors import AcquisitionError, PublicationNotFound


def router(service):
    api = APIRouter(prefix="/pubmed/api", tags=["pubmed"])

    def call(action, *args):
        try:
            return action(*args)
        except PublicationNotFound as exc:
            raise HTTPException(404, "Query or request not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except AcquisitionError as exc:
            raise HTTPException(502, str(exc)) from exc

    @api.post("/search")
    def search(body: Annotated[dict, Body()]):
        return call(service.search, body)

    @api.get("/queries")
    def queries():
        return {"queries": service.queries()}

    @api.get("/queries/{query_id}/papers")
    def papers(query_id: str):
        return {"papers": call(service.papers, query_id)}

    @api.post("/requests", status_code=201)
    def submit(body: Annotated[dict, Body()]):
        return call(service.submit, body)

    @api.get("/requests")
    def requests():
        return {"requests": service.requests()}

    @api.get("/requests/{request_id}")
    def request(request_id: str):
        return call(lambda: service.one("run_requests", request_id=request_id))

    @api.post("/requests/{request_id}/retry", status_code=201)
    def retry(request_id: str):
        return call(service.retry, request_id)

    return api
