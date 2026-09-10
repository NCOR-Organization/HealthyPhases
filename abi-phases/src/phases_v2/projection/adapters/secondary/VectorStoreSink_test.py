"""The vector sink, against the service API the engine really provides.

The earlier version called the *adapter's* method names and passed its unit
tests because they used SqliteVecAdapter directly. Production hands out a
VectorStoreService, so it only failed in a real run. These tests use a double
shaped like the service.
"""

from contextlib import closing
from uuid import UUID

import numpy as np

from phases_v2.projection.adapters.secondary.VectorStoreSink import VectorStoreSink
from phases_v2.projection.interfaces import VectorDoc


class _ServiceDouble:
    """Only the methods VectorStoreService actually exposes."""

    def __init__(self):
        self.collections = {}
        self.added = []

    def ensure_collection(self, collection_name, dimension, **kwargs):
        self.collections[collection_name] = dimension

    def add_documents(
        self, collection_name, ids, vectors, metadata=None, payloads=None
    ):
        self.added.append((collection_name, ids, vectors, metadata, payloads))


def _doc(doc_id="i0", text="a claim", **metadata):
    return VectorDoc(id=doc_id, text=text, metadata=metadata or {"chunk_id": "c0"})


def test_it_uses_the_services_own_method_names():
    service = _ServiceDouble()

    VectorStoreSink(service).ensure_collection("phases_v2_chunks", 3072)

    assert service.collections == {"phases_v2_chunks": 3072}


def test_documents_are_added_with_ids_vectors_metadata_and_payload():
    service = _ServiceDouble()

    VectorStoreSink(service).store("c", [_doc()], [[0.1, 0.2]])

    [(name, ids, vectors, metadata, payloads)] = service.added
    assert name == "c"
    assert len(ids) == 1
    assert UUID(ids[0]).version == 5
    assert vectors[0].dtype == np.float32
    assert metadata == [{"chunk_id": "c0", "document_id": "i0"}]
    assert payloads == [{"text": "a claim"}]


def test_null_metadata_is_dropped_rather_than_stored():
    service = _ServiceDouble()

    VectorStoreSink(service).store("c", [_doc(model_id=None, chunk_id="c0")], [[0.1]])

    [(_n, _i, _v, metadata, _p)] = service.added
    assert metadata == [{"chunk_id": "c0", "document_id": "i0"}]


def test_storing_nothing_does_not_call_the_service():
    service = _ServiceDouble()

    VectorStoreSink(service).store("c", [], [])

    assert service.added == []


def test_the_sink_only_calls_methods_the_service_defines():
    # The guard for the actual bug: a method the service does not have would
    # pass a duck-typed double but explode in production.
    from naas_abi_core.services.vector_store.VectorStoreService import (
        VectorStoreService,
    )

    for name in ("ensure_collection", "add_documents"):
        assert hasattr(VectorStoreService, name), name
    for name in ("create_collection", "store_vectors"):
        assert not hasattr(VectorStoreService, name), (
            f"{name} is the adapter's API, not the service's"
        )


def test_retries_use_the_same_uuid_and_distinct_rows_stay_distinct():
    service = _ServiceDouble()
    sink = VectorStoreSink(service)
    sink.store("chunks", [_doc("a" * 64), _doc("b" * 64)], [[1.0], [0.5]])
    sink.store("chunks", [_doc("a" * 64)], [[0.9]])
    sink.store("items", [_doc("a" * 64)], [[0.8]])
    first, retry, other_collection = [entry[1] for entry in service.added]
    assert first[0] == retry[0]
    assert len({*first, *other_collection}) == 3
    assert all(UUID(point_id).version == 5 for point_id in first)


def test_actual_qdrant_adapter_accepts_hash_ids_and_upserts_on_retry():
    from naas_abi_core.services.vector_store.adapters.QdrantAdapter import QdrantAdapter
    from naas_abi_core.services.vector_store.VectorStoreService import (
        VectorStoreService,
    )
    from qdrant_client import QdrantClient

    with closing(QdrantClient(":memory:")) as client:
        adapter = QdrantAdapter()
        adapter.client = client
        sink = VectorStoreSink(VectorStoreService(adapter))
        sink.ensure_collection("phases_v2_chunks", 2)
        doc = _doc("a" * 64, text="original", chunk_id="a" * 64)
        sink.store("phases_v2_chunks", [doc], [[1.0, 0.0]])
        sink.store("phases_v2_chunks", [doc], [[0.0, 1.0]])
        points, _ = client.scroll("phases_v2_chunks", with_vectors=True)
        assert len(points) == 1
        assert UUID(points[0].id).version == 5
        assert points[0].payload["document_id"] == doc.id
        assert points[0].payload["chunk_id"] == doc.id
        assert points[0].payload["payload"]["text"] == "original"
        assert points[0].vector == [0.0, 1.0]
