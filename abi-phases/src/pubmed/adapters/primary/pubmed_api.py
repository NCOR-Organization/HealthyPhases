"""HTTP mapping for the Nexus app. Downloads run only in the worker."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from naas_abi_core.apps.api.abi_api_key_auth import require_abi_api_token

from pubmed.application.pubmed_schedules import PubmedSchedules
from pubmed.domain.pubmed_errors import AcquisitionError, PublicationNotFound


def router(service):
    api = APIRouter(prefix="/pubmed/api", tags=["pubmed"])
    schedules = PubmedSchedules(service)

    def call(action, *args):
        try:
            return action(*args)
        except PublicationNotFound as exc:
            raise HTTPException(404, "Query, request or schedule not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except AcquisitionError as exc:
            raise HTTPException(502, str(exc)) from exc

    @api.post("/search", dependencies=[Depends(require_abi_api_token)])
    def search(body: Annotated[dict, Body()]):
        return call(service.search, body)

    @api.get("/schedules")
    def list_schedules():
        return {"schedules": schedules.list()}

    @api.post(
        "/schedules", status_code=201, dependencies=[Depends(require_abi_api_token)]
    )
    def create_schedule(body: Annotated[dict, Body()]):
        return call(schedules.create, body)

    @api.patch(
        "/schedules/{schedule_id}", dependencies=[Depends(require_abi_api_token)]
    )
    def toggle_schedule(schedule_id: str, body: Annotated[dict, Body()]):
        return call(schedules.toggle, schedule_id, body)

    @api.delete(
        "/schedules/{schedule_id}",
        status_code=204,
        dependencies=[Depends(require_abi_api_token)],
    )
    def delete_schedule(schedule_id: str):
        call(schedules.delete, schedule_id)
        return Response(status_code=204)

    @api.get("/queries")
    def queries():
        return {"queries": service.queries()}

    @api.get("/queries/{query_id}/papers")
    def papers(query_id: str):
        return {"papers": call(service.papers, query_id)}

    @api.post(
        "/requests", status_code=201, dependencies=[Depends(require_abi_api_token)]
    )
    def submit(body: Annotated[dict, Body()]):
        return call(service.submit, body)

    @api.get("/requests")
    def requests():
        return {"requests": service.requests()}

    @api.get("/requests/{request_id}")
    def request(request_id: str):
        return call(lambda: service.one("run_requests", request_id=request_id))

    @api.post(
        "/requests/{request_id}/retry",
        status_code=201,
        dependencies=[Depends(require_abi_api_token)],
    )
    def retry(request_id: str):
        return call(service.retry, request_id)

    return api
