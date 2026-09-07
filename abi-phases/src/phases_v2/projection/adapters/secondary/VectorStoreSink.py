"""The engine's vector store, as the projectors' :class:`VectorSink`.

Ids are the content-addressed row ids and the store upserts by id, so
re-storing a doc replaces it rather than adding a second copy.
"""

from __future__ import annotations

import numpy as np
from naas_abi_core.services.vector_store.IVectorStorePort import VectorDocument


class VectorStoreSink:
    def __init__(self, vector_store):
        self._vector_store = vector_store

    def ensure_collection(self, name: str, dimension: int) -> None:
        if name not in self._vector_store.list_collections():
            self._vector_store.create_collection(name, dimension)

    def store(self, name, docs, vectors) -> None:
        if not docs:
            return
        self._vector_store.store_vectors(
            name,
            [
                VectorDocument(
                    id=doc.id,
                    vector=np.asarray(vector, dtype=np.float32),
                    # Metadata is what a search hit resolves back through, and
                    # a null value is not worth a column in every payload.
                    metadata={
                        key: value
                        for key, value in doc.metadata.items()
                        if value is not None
                    },
                    payload={"text": doc.text},
                )
                for doc, vector in zip(docs, vectors)
            ],
        )
