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
