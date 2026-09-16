"""The semantic adapter, against a real (sqlite-vec) vector store.

The embedder is faked — real embeddings cost money and need a key — but the
vector store and the write path (``VectorStoreSink``, the same one the
projector uses) are real, which is where the metadata round-trip this adapter
depends on actually lives.
"""

from __future__ import annotations

from naas_abi_core.services.vector_store.adapters.SqliteVecAdapter import (
    SqliteVecAdapter,
)
from naas_abi_core.services.vector_store.VectorStoreService import VectorStoreService

from phases_v2.projection.adapters.secondary.VectorStoreSink import VectorStoreSink
from phases_v2.projection.fakes import FakeEmbedder
from phases_v2.projection.interfaces import VectorDoc
from phases_v2.projection.vectors import ITEMS_COLLECTION
from phases_v2.search.adapters.secondary.VectorStoreSemanticAdapter import (
    VectorStoreSemanticAdapter,
)
from phases_v2.search.contracts import assert_semantic_index_contract, canonical_items


def _seeded_store(tmp_path):
    store = VectorStoreService(
        adapter=SqliteVecAdapter(persistence_path=str(tmp_path / "vectors.sqlite3"))
    )
    store.initialize()
    embedder = FakeEmbedder()
    items = canonical_items()
    docs = [VectorDoc(id=item.item_id, text=item.text, metadata={}) for item in items]
    vectors = embedder.embed([doc.text for doc in docs])
    store.ensure_collection(ITEMS_COLLECTION, embedder.dimension)
    VectorStoreSink(store).store(ITEMS_COLLECTION, docs, vectors)
    return store


def test_the_contract(tmp_path):
    adapter = VectorStoreSemanticAdapter(_seeded_store(tmp_path), FakeEmbedder())

    assert_semantic_index_contract(adapter)


def test_a_missing_collection_is_reported_as_no_results(tmp_path):
    store = VectorStoreService(
        adapter=SqliteVecAdapter(persistence_path=str(tmp_path / "empty.sqlite3"))
    )
    store.initialize()
    adapter = VectorStoreSemanticAdapter(store, FakeEmbedder())

    assert adapter.search("anything", k=5) == []


def test_qdrant_filters_models_before_top_k_and_merges_selected_models():
    from contextlib import closing
    from types import SimpleNamespace

    from naas_abi_core.services.vector_store.adapters.QdrantAdapter import QdrantAdapter
    from qdrant_client import QdrantClient

    with closing(QdrantClient(":memory:")) as client:
        port = QdrantAdapter()
        port.client = client
        store = VectorStoreService(port)
        sink = VectorStoreSink(store)
        sink.ensure_collection(ITEMS_COLLECTION, 2)
        docs = [
            VectorDoc(id=f"other-{i}", text="other", metadata={"model_id": "other"})
            for i in range(20)
        ]
        docs += [
            VectorDoc(
                id="a",
                text="first",
                metadata={"model_id": "model-a", "paper_id": "paper-a"},
            ),
            VectorDoc(
                id="b",
                text="second",
                metadata={"model_id": "model-b", "paper_id": "paper-b"},
            ),
        ]
        sink.store(ITEMS_COLLECTION, docs, [[1.0, 0.0]] * 20 + [[0.8, 0.6], [0.6, 0.8]])
        calls = []

        def embed(texts):
            calls.append(texts)
            return [[1.0, 0.0]]

        index = VectorStoreSemanticAdapter(store, SimpleNamespace(embed=embed))
        assert [m.item_id for m in index.search("claim", k=1, models=["model-a"])] == [
            "a"
        ]
        calls.clear()
        hits = index.search("claim", k=2, models=["model-b", "model-a", "model-a"])
        assert [m.item_id for m in hits] == ["a", "b"]
        assert len(calls) == 1
        assert index.search("claim", k=1, models=["unknown"]) == []
        assert index.search("claim", k=1, models=["model-a"], score_threshold=0.9) == []
        assert [
            m.item_id for m in index.search("claim", k=1, paper_ids=["paper-b"])
        ] == ["b"]
        assert (
            index.search("claim", k=1, models=["model-a"], paper_ids=["paper-b"]) == []
        )
        assert [
            m.item_id
            for m in index.search(
                "claim", k=2, paper_ids=["paper-a", "paper-b", "paper-a"]
            )
        ] == ["a", "b"]
        calls.clear()
        assert index.search("claim", k=1, paper_ids=[]) == []
        assert calls == []


def test_complete_semantic_search_exceeds_one_hundred_with_stable_score_ties():
    from contextlib import closing
    from types import SimpleNamespace

    from naas_abi_core.services.vector_store.adapters.QdrantAdapter import QdrantAdapter
    from qdrant_client import QdrantClient

    with closing(QdrantClient(":memory:")) as client:
        port = QdrantAdapter()
        port.client = client
        store = VectorStoreService(port)
        sink = VectorStoreSink(store)
        sink.ensure_collection(ITEMS_COLLECTION, 2)
        docs = [
            VectorDoc(id=f"item-{i:04d}", text="claim", metadata={"model_id": "m"})
            for i in range(205)
        ]
        sink.store(ITEMS_COLLECTION, docs, [[1.0, 0.0]] * 205)
        adapter = VectorStoreSemanticAdapter(
            store, SimpleNamespace(embed=lambda texts: [[1.0, 0.0]])
        )
        matches = adapter.search_all("claim", models=["m"])
        assert [m.item_id for m in matches] == [doc.id for doc in docs]
        assert adapter.search_all("claim", models=["missing"]) == []
