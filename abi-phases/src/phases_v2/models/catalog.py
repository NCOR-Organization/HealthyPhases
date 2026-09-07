"""The AI models this module may run extractions with.

A declaration is metadata, not a client: it names a model and says which
provider and provider-side id it maps to. The live chat model is built at
extraction time through the engine's model registry, so nothing here needs
credentials and the catalog can be listed by a webapp that has none.

``model_id`` is the identity recorded against every extraction, so it must stay
stable. Withdrawing a model from this list stops new runs from choosing it and
leaves existing rows readable and attributable.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from phases_v2.ports import RowStore


class UnknownModelError(Exception):
    """A run named a model that is not declared."""


@dataclass(frozen=True)
class ModelDeclaration:
    model_id: str
    provider: str
    provider_model_id: str
    display_name: str


DECLARED_MODELS: tuple[ModelDeclaration, ...] = (
    ModelDeclaration(
        model_id="openai/gpt-4.1-mini",
        provider="openai",
        provider_model_id="gpt-4.1-mini",
        display_name="GPT-4.1 mini",
    ),
    ModelDeclaration(
        model_id="openai/gpt-5-mini",
        provider="openai",
        provider_model_id="gpt-5-mini",
        display_name="GPT-5 mini",
    ),
    ModelDeclaration(
        model_id="google/gemini-2.0-flash",
        provider="google",
        provider_model_id="gemini-2.0-flash",
        display_name="Gemini 2.0 Flash",
    ),
)

_BY_ID = {model.model_id: model for model in DECLARED_MODELS}


def resolve(model_id: str) -> ModelDeclaration:
    """Return the declaration for ``model_id``.

    Raises :class:`UnknownModelError` rather than letting a run reach the point
    of writing rows against a model nobody declared.
    """
    model = _BY_ID.get(model_id)
    if model is None:
        raise UnknownModelError(
            f"{model_id!r} is not a declared model; "
            f"declared models are {', '.join(sorted(_BY_ID))}"
        )
    return model


def register_models(store: RowStore, models: list[ModelDeclaration]) -> list[str]:
    """Publish every declared model. Returns their ids, in declaration order."""
    ids = [model.model_id for model in models]
    repeated = [value for value, count in Counter(ids).items() if count > 1]
    if repeated:
        raise ValueError(
            "the same model was declared twice: " + ", ".join(sorted(repeated))
        )
    if not models:
        return []

    now = datetime.now(UTC)
    store.write_rows(
        "models",
        [
            {
                "model_id": model.model_id,
                "provider": model.provider,
                "provider_model_id": model.provider_model_id,
                "display_name": model.display_name,
                "registered_at": now,
            }
            for model in models
        ],
    )
    return ids
