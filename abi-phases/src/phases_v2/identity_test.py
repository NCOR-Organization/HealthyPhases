"""Ids are content-addressed so that every stage is idempotent for free.

One id serves four purposes: the dataset primary key, the vector id, the local
name of the RDF URI, and (for a run request) the Dagster run key. So two
properties matter everywhere: the same inputs always give the same id, and any
differing input gives a different one.
"""

from phases_v2 import identity


def test_paper_id_is_derived_from_content_not_location():
    assert identity.paper_id(b"same bytes") == identity.paper_id(b"same bytes")
    assert identity.paper_id(b"a") != identity.paper_id(b"b")


def test_chunker_id_changes_with_name_version_or_params():
    base = identity.chunker_id("window", "1", {"size": 512, "overlap": 128})

    assert base == identity.chunker_id("window", "1", {"size": 512, "overlap": 128})
    assert base != identity.chunker_id("window", "2", {"size": 512, "overlap": 128})
    assert base != identity.chunker_id("other", "1", {"size": 512, "overlap": 128})
    assert base != identity.chunker_id("window", "1", {"size": 256, "overlap": 128})


def test_chunker_id_does_not_depend_on_param_ordering():
    assert identity.chunker_id("w", "1", {"a": 1, "b": 2}) == identity.chunker_id(
        "w", "1", {"b": 2, "a": 1}
    )


def test_chunker_id_carries_a_readable_prefix():
    # The id ends up in dataset rows and partition values a human will read.
    assert identity.chunker_id("window", "1", {}).startswith("window_1_")


def test_chunk_id_changes_with_paper_chunker_or_position():
    base = identity.chunk_id("paper", "chunker", 0)

    assert base == identity.chunk_id("paper", "chunker", 0)
    assert base != identity.chunk_id("other", "chunker", 0)
    assert base != identity.chunk_id("paper", "other", 0)
    assert base != identity.chunk_id("paper", "chunker", 1)


def test_prompt_id_changes_only_when_the_template_text_changes():
    base = identity.prompt_id("solitude", "Extract from {chunk_text}")

    assert base == identity.prompt_id("solitude", "Extract from {chunk_text}")
    assert base != identity.prompt_id("solitude", "Extract ALL from {chunk_text}")
    assert base != identity.prompt_id("other", "Extract from {chunk_text}")


def test_prompt_id_carries_a_readable_prefix():
    assert identity.prompt_id("solitude", "x").startswith("solitude_")


def test_extraction_id_changes_with_chunk_model_or_prompt():
    base = identity.extraction_id("chunk", "model", "prompt")

    assert base == identity.extraction_id("chunk", "model", "prompt")
    assert base != identity.extraction_id("other", "model", "prompt")
    assert base != identity.extraction_id("chunk", "other", "prompt")
    assert base != identity.extraction_id("chunk", "model", "other")


def test_extraction_id_components_cannot_be_confused_for_one_another():
    # A naive concatenation would make ("ab", "c", "d") and ("a", "bc", "d")
    # collide. The separator has to be one the components cannot contain, or
    # the components have to be length-delimited.
    assert identity.extraction_id("ab", "c", "d") != identity.extraction_id(
        "a", "bc", "d"
    )


def test_item_id_changes_with_extraction_or_position():
    base = identity.item_id("extraction", 0)

    assert base == identity.item_id("extraction", 0)
    assert base != identity.item_id("extraction", 1)
    assert base != identity.item_id("other", 0)


def test_ids_are_safe_as_uri_local_names_and_vector_ids():
    ids = [
        identity.paper_id(b"x"),
        identity.chunk_id("p", "c", 0),
        identity.extraction_id("c", "m", "p"),
        identity.item_id("e", 0),
        identity.chunker_id("window", "1", {}),
        identity.prompt_id("solitude", "x"),
    ]
    for value in ids:
        assert value
        assert all(ch.isalnum() or ch in "_-" for ch in value), value
