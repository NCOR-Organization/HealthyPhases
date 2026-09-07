"""Which AI models the pipeline may run extractions with.

The catalog exists so the webapp can offer a chooser and so a run cannot name
a model nobody declared.
"""

import pytest

from phases_v2.fakes import InMemoryRowStore
from phases_v2.models.catalog import (
    DECLARED_MODELS,
    ModelDeclaration,
    UnknownModelError,
    register_models,
    resolve,
)


def _model(model_id="openai/gpt-4.1-mini"):
    return ModelDeclaration(
        model_id=model_id,
        provider="openai",
        provider_model_id="gpt-4.1-mini",
        display_name="GPT-4.1 mini",
    )


def test_declared_models_are_published_for_a_client_to_list():
    store = InMemoryRowStore()

    registered = register_models(store, [_model()])

    assert registered == ["openai/gpt-4.1-mini"]
    [row] = store.rows("models")
    assert row["provider"] == "openai"
    assert row["provider_model_id"] == "gpt-4.1-mini"
    assert row["display_name"] == "GPT-4.1 mini"
    assert row["registered_at"] is not None


def test_restarting_unchanged_leaves_one_row_per_model():
    store = InMemoryRowStore()

    register_models(store, [_model()])
    register_models(store, [_model()])

    assert store.count("models") == 1


def test_declaring_the_same_id_twice_is_rejected():
    store = InMemoryRowStore()

    with pytest.raises(ValueError, match="declared twice"):
        register_models(store, [_model(), _model()])


def test_resolving_a_declared_model_returns_it():
    assert resolve(DECLARED_MODELS[0].model_id) is DECLARED_MODELS[0]


def test_resolving_an_undeclared_model_names_it_and_lists_what_is_available():
    with pytest.raises(UnknownModelError) as raised:
        resolve("openai/not-a-real-model")

    message = str(raised.value)
    assert "openai/not-a-real-model" in message
    assert DECLARED_MODELS[0].model_id in message


def test_the_module_declares_at_least_one_model():
    assert DECLARED_MODELS


def test_declared_model_ids_are_unique():
    ids = [model.model_id for model in DECLARED_MODELS]
    assert len(ids) == len(set(ids))


def test_every_declared_model_states_its_provider_and_provider_id():
    for model in DECLARED_MODELS:
        assert model.provider
        assert model.provider_model_id
        assert model.display_name


def test_registering_nothing_is_not_an_error():
    store = InMemoryRowStore()

    assert register_models(store, []) == []
    assert store.count("models") == 0


def test_claude_is_declared_and_routed_through_openrouter():
    # `naas_abi_marketplace.ai.openrouter` registers these under provider
    # "openrouter" with the vendor-prefixed slug as the model id; the
    # declaration must match or the registry lookup cannot find it.
    sonnet = resolve("openrouter/claude-sonnet-4.6")

    assert sonnet.provider == "openrouter"
    # The registry's canonical id, not OpenRouter's "anthropic/..." slug.
    assert sonnet.provider_model_id == "claude-sonnet-4.6"
    assert "Claude Sonnet" in sonnet.display_name


def test_the_route_is_visible_in_the_model_id():
    # model_id is recorded against every extraction, so "which model produced
    # this" should also say how it was reached.
    for model in DECLARED_MODELS:
        assert model.model_id.startswith(model.provider + "/")
