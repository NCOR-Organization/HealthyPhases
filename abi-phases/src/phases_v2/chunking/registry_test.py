"""Chunking mechanisms are declared in code and published on start.

A chunker's identity is its parameters, so changing one produces a new
mechanism rather than redefining the one existing chunks were made with.
"""

import pytest

from phases_v2 import identity
from phases_v2.chunking.registry import Chunker, register_chunkers
from phases_v2.fakes import InMemoryRowStore


def _chunker(name="window", version="1", **params):
    return Chunker(name=name, version=version, params=params or {"size": 512})


def test_declared_chunkers_are_recorded_on_start():
    store = InMemoryRowStore()

    registered = register_chunkers(store, [_chunker()])

    assert registered == [identity.chunker_id("window", "1", {"size": 512})]
    [row] = store.rows("chunkers")
    assert row["name"] == "window"
    assert row["version"] == "1"
    assert row["params"] == {"size": 512}
    assert row["registered_at"] is not None


def test_changing_a_parameter_registers_a_new_mechanism():
    store = InMemoryRowStore()
    register_chunkers(store, [_chunker(size=512)])

    register_chunkers(store, [_chunker(size=256)])

    assert store.count("chunkers") == 2


def test_the_previous_mechanism_survives_a_parameter_change():
    store = InMemoryRowStore()
    before = register_chunkers(store, [_chunker(size=512)])[0]

    register_chunkers(store, [_chunker(size=256)])

    assert before in {row["chunker_id"] for row in store.rows("chunkers")}


def test_restarting_unchanged_leaves_one_row_per_mechanism():
    store = InMemoryRowStore()

    register_chunkers(store, [_chunker()])
    register_chunkers(store, [_chunker()])

    assert store.count("chunkers") == 1


def test_parameter_ordering_does_not_change_identity():
    store = InMemoryRowStore()

    register_chunkers(store, [Chunker("w", "1", {"a": 1, "b": 2})])
    register_chunkers(store, [Chunker("w", "1", {"b": 2, "a": 1})])

    assert store.count("chunkers") == 1


def test_registering_nothing_is_not_an_error():
    store = InMemoryRowStore()

    assert register_chunkers(store, []) == []
    assert store.count("chunkers") == 0


def test_two_chunkers_declared_with_the_same_id_are_rejected():
    store = InMemoryRowStore()

    with pytest.raises(ValueError, match="declared twice"):
        register_chunkers(store, [_chunker(), _chunker()])
