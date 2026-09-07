"""Prompt templates live in code and are published to a dataset on start.

The point of the registry is provenance: editing a template must produce a new
version rather than redefining the one that existing extractions were produced
with.
"""

import pytest

from phases_v2 import identity
from phases_v2.fakes import InMemoryRowStore
from phases_v2.prompts.domain import PromptTemplate, register_prompts


def _template(name="solitude", text="Find claims in {chunk_text}", key="results"):
    return PromptTemplate(name=name, template=text, output_key=key)


def test_declared_templates_are_recorded_on_start():
    store = InMemoryRowStore()

    registered = register_prompts(store, [_template()])

    assert registered == [identity.prompt_id("solitude", "Find claims in {chunk_text}")]
    [row] = store.rows("prompts")
    assert row["name"] == "solitude"
    assert row["template"] == "Find claims in {chunk_text}"
    assert row["output_key"] == "results"
    assert row["prompt_sha256"] == identity.prompt_sha256(
        "Find claims in {chunk_text}"
    )
    assert row["registered_at"] is not None


def test_editing_a_template_adds_a_version_and_leaves_the_old_one_intact():
    store = InMemoryRowStore()
    register_prompts(store, [_template(text="Find claims in {chunk_text}")])

    register_prompts(store, [_template(text="Find ALL claims in {chunk_text}")])

    ids = {row["prompt_id"] for row in store.rows("prompts")}
    assert len(ids) == 2
    templates = {row["template"] for row in store.rows("prompts")}
    assert "Find claims in {chunk_text}" in templates


def test_restarting_with_unchanged_templates_leaves_one_row_per_version():
    store = InMemoryRowStore()

    register_prompts(store, [_template()])
    register_prompts(store, [_template()])

    assert store.count("prompts") == 1


def test_a_template_without_the_chunk_placeholder_is_rejected():
    store = InMemoryRowStore()

    with pytest.raises(ValueError, match="chunk_text"):
        register_prompts(store, [_template(text="Find claims in the text")])


def test_a_rejected_template_records_nothing():
    store = InMemoryRowStore()

    with pytest.raises(ValueError):
        register_prompts(
            store, [_template(), _template(name="bad", text="no placeholder")]
        )

    # Validation happens before any write, so a bad declaration cannot leave
    # the dataset holding half a registration.
    assert store.count("prompts") == 0


def test_the_offending_template_is_named():
    store = InMemoryRowStore()

    with pytest.raises(ValueError, match="bad"):
        register_prompts(store, [_template(name="bad", text="no placeholder")])


def test_two_templates_may_share_text_under_different_names():
    store = InMemoryRowStore()

    register_prompts(store, [_template(name="a"), _template(name="b")])

    assert store.count("prompts") == 2


def test_registering_nothing_is_not_an_error():
    store = InMemoryRowStore()

    assert register_prompts(store, []) == []
    assert store.count("prompts") == 0
