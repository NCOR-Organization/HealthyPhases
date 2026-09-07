"""Wiring for the pipeline app."""

from __future__ import annotations

from functools import lru_cache

from phases_v2.app.service import PipelineAppService
from phases_v2.papers.adapters.secondary.PdfTextRenderer import PdfTextRenderer
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.requests.factory import request_store


def model_availability(engine):
    """Whether the registry can build each declared model, in this deployment.

    Resolution is what actually fails — a model can be declared here and still
    have no provider registered, which is the case for `google` unless a module
    contributes one. Cached because building a client is not free and the
    answer cannot change without a restart.
    """

    @lru_cache(maxsize=None)
    def available(model_id: str) -> bool:
        from phases_v2.extraction.factory import model_for

        try:
            model_for(engine, model_id)
        except Exception:  # noqa: BLE001 - any resolution failure means unusable
            return False
        return True

    return available


def app_service(engine, papers_root: str = "phases_v2") -> PipelineAppService:
    return PipelineAppService(
        papers_root=papers_root,
        request_store=request_store(engine),
        object_storage=engine.services.object_storage,
        rows=DatasetRowStore(engine.services.dataset),
        is_model_available=model_availability(engine),
        renderer=PdfTextRenderer(),
    )
