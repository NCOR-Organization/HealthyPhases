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
    #: Recorded against every extraction. Prefixed with the provider so the
    #: route a claim was produced through stays visible.
    model_id: str
    #: Which provider's factory the registry should route through.
    provider: str
    #: The registry's *canonical* id for the model — not necessarily the
    #: provider's own slug. OpenRouter serves "anthropic/claude-sonnet-4.6"
    #: but the registry is keyed on "claude-sonnet-4.6".
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
    # Anthropic is reached through OpenRouter rather than direct: one key
    # covers every vendor. `provider_model_id` is the registry's canonical id
    # ("claude-sonnet-4.6"), not OpenRouter's vendor-prefixed slug
    # ("anthropic/claude-sonnet-4.6") — the registry is keyed on the former and
    # the lookup fails with the latter. The `model_id` keeps the route visible,
    # because it is recorded against every extraction and "which model produced
    # this" should include how it was called.
    ModelDeclaration(
        model_id="openrouter/claude-sonnet-4.6",
        provider="openrouter",
        provider_model_id="claude-sonnet-4.6",
        display_name="Claude Sonnet 4.6 (OpenRouter)",
    ),
    ModelDeclaration(
        model_id="openrouter/claude-haiku-4.5",
        provider="openrouter",
        provider_model_id="claude-haiku-4.5",
        display_name="Claude Haiku 4.5 (OpenRouter)",
    ),
    # Also via OpenRouter: the direct `google` provider registers nothing
    # unless a GOOGLE_API_KEY is configured, whereas this route already works.
    ModelDeclaration(
        model_id="openrouter/gemini-3.1-pro-preview",
        provider="openrouter",
        provider_model_id="gemini-3.1-pro-preview",
        display_name="Gemini 3.1 Pro (OpenRouter)",
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
