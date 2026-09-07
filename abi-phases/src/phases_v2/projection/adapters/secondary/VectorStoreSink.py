"""The engine's vector store, as the projectors' :class:`VectorSink`.

Written against ``VectorStoreService`` — the type the engine actually hands
out. The underlying adapter exposes ``create_collection``/``store_vectors``,
but the service wraps those as ``ensure_collection``/``add_documents``, and an
earlier version of this file called the adapter's names and only failed in a
real run.

Ids are the content-addressed row ids and the store upserts by id, so
re-storing a doc replaces it rather than adding a second copy.
"""

from __future__ import annotations

import numpy as np


class VectorStoreSink:
    def __init__(self, vector_store):
        self._vector_store = vector_store

    def ensure_collection(self, name: str, dimension: int) -> None:
        self._vector_store.ensure_collection(name, dimension)

    def store(self, name, docs, vectors) -> None:
        if not docs:
            return
        self._vector_store.add_documents(
            collection_name=name,
            ids=[doc.id for doc in docs],
            vectors=[np.asarray(vector, dtype=np.float32) for vector in vectors],
            # Metadata is what a search hit resolves back through, and a null
            # value is not worth a key in every payload.
            metadata=[
                {k: v for k, v in doc.metadata.items() if v is not None}
                for doc in docs
            ],
            payloads=[{"text": doc.text} for doc in docs],
        )
