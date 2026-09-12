"""The engine's vector store, as the projectors' :class:`VectorSink`.

Written against ``VectorStoreService`` — the type the engine actually hands
out. The underlying adapter exposes ``create_collection``/``store_vectors``,
but the service wraps those as ``ensure_collection``/``add_documents``, and an
earlier version of this file called the adapter's names and only failed in a
real run.

Qdrant point IDs are deterministic UUIDs derived from the collection and row
ID. Original row IDs remain in metadata and the projection ledger, while
re-storing a document upserts the same point.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

import numpy as np


class VectorStoreSink:
    def __init__(self, vector_store):
        self._vector_store = vector_store

    def ensure_collection(self, name: str, dimension: int) -> None:
        self._vector_store.ensure_collection(name, dimension)
        if name == "phases_v2_extracted_items":
            from naas_abi_core.services.vector_store.adapters.QdrantAdapter import (
                QdrantAdapter,
            )

            from phases_v2.projection.adapters.secondary.QdrantMetadataSink import (
                QdrantMetadataSink,
            )

            if isinstance(self._vector_store.adapter, QdrantAdapter):
                QdrantMetadataSink(self._vector_store.adapter.client).ensure_indexes()

    def store(self, name, docs, vectors) -> None:
        if not docs:
            return
        self._vector_store.add_documents(
            collection_name=name,
            ids=[
                str(uuid5(NAMESPACE_URL, f"phases_v2/{name}/{doc.id}")) for doc in docs
            ],
            vectors=[np.asarray(vector, dtype=np.float32) for vector in vectors],
            # Metadata is what a search hit resolves back through, and a null
            # value is not worth a key in every payload.
            metadata=[
                {k: v for k, v in doc.metadata.items() if v is not None}
                | {"document_id": doc.id}
                for doc in docs
            ],
            payloads=[{"text": doc.text} for doc in docs],
        )
