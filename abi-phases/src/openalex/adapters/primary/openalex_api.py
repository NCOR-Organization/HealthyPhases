"""Authenticated mutations enqueue work; HTTP requests never call OpenAlex."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from naas_abi_core.apps.api.abi_api_key_auth import require_abi_api_token

from openalex.contracts.openalex_validation import validate
from openalex.domain.openalex_errors import EnrichmentNotFound


def router(service):
    api = APIRouter(prefix="/openalex/api", tags=["openalex"])

    def call(action, *args):
        try:
            return action(*args)
        except EnrichmentNotFound as exc:
            raise HTTPException(404, "Saved query or enrichment not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @api.get("/status")
    def status():
        return validate(
            "ServiceStatus",
            {
                "available": True,
                "api_key_configured": bool(service.source.api_key),
                "request_budget": service.request_budget,
                "cache_days": service.cache_days,
            },
        )

    @api.get("/queries")
    def queries():
        return validate(
            "QueryList",
            {
                "queries": [
                    {k: row[k] for k in ("query_id", "query", "created_at")}
                    for row in service.catalog.queries()
                ]
            },
        )

    @api.get("/requests")
    def requests():
        return validate("RequestList", {"requests": service.requests()})

    @api.post(
        "/requests", status_code=201, dependencies=[Depends(require_abi_api_token)]
    )
    def create(body: Annotated[dict, Body()]):
        return call(service.create, body)

    @api.post(
        "/requests/{request_id}/resume", dependencies=[Depends(require_abi_api_token)]
    )
    def resume(request_id: str):
        return call(service.resume, request_id)

    @api.get("/papers/{pmid}")
    def detail(pmid: str):
        return validate("PaperDetail", call(service.detail, pmid))

    return api
