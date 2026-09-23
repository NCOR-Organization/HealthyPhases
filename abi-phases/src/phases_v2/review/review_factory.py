"""Composition root for bounded operator-invoked review runs."""

from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.models.catalog import resolve
from phases_v2.review.contracts.review_validation import validate_batch
from phases_v2.review.review_model import LangchainReviewModel
from phases_v2.review.review_service import ReviewService


def service_for(engine):
    return ReviewService(DatasetRowStore(engine.services.dataset), validate_batch)


def model_for(engine, model_id):
    declared = resolve(model_id)
    chat = engine.services.model_registry.get(
        declared.provider_model_id, provider=declared.provider
    ).model
    if not all(
        hasattr(chat, field)
        for field in ("max_retries", "request_timeout", "temperature")
    ):
        raise ValueError(
            "Reviewer requires a chat adapter with explicit retry and timeout controls"
        )
    chat = chat.model_copy(
        update={"max_retries": 0, "request_timeout": 120, "temperature": 0}
    )
    return LangchainReviewModel(chat)
