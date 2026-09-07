"""Wiring for the pipeline app."""

from __future__ import annotations

from phases_v2.app.service import PipelineAppService
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.requests.factory import request_store


def app_service(engine) -> PipelineAppService:
    return PipelineAppService(
        request_store=request_store(engine),
        object_storage=engine.services.object_storage,
        rows=DatasetRowStore(engine.services.dataset),
    )
