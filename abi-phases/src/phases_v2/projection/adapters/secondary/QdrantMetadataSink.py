"""Update existing Qdrant payloads and create indexes for search filters."""

from qdrant_client import models as qm

from phases_v2.projection.vectors import ITEMS_COLLECTION


class QdrantMetadataSink:
    def __init__(self, client):
        self._client = client

    def ensure_indexes(self):
        existing = self._client.get_collection(ITEMS_COLLECTION).payload_schema
        for key in ["prompt_name", "model_id", "paper_id", "source_ancestors"]:
            if key not in existing:
                self._client.create_payload_index(
                    ITEMS_COLLECTION, key, qm.PayloadSchemaType.KEYWORD, wait=True
                )
        if "search_metadata_version" not in existing:
            self._client.create_payload_index(
                ITEMS_COLLECTION,
                "search_metadata_version",
                qm.PayloadSchemaType.INTEGER,
                wait=True,
            )

    def refresh(self, metadata):
        if not self._client.collection_exists(ITEMS_COLLECTION):
            return 0
        self.ensure_indexes()
        offset, updated = None, 0
        while True:
            records, offset = self._client.scroll(
                ITEMS_COLLECTION,
                limit=128,
                offset=offset,
                with_payload=["item_id", "document_id"],
                with_vectors=False,
            )
            operations = []
            for point in records:
                payload = point.payload or {}
                item_id = payload.get("item_id") or payload.get("document_id")
                if item_id not in metadata:
                    raise ValueError(
                        f"No dataset metadata for vector {point.id}; refresh aborted"
                    )
                operations.append(
                    qm.SetPayloadOperation(
                        set_payload=qm.SetPayload(
                            payload=metadata[item_id], points=[point.id]
                        )
                    )
                )
            if operations:
                self._client.batch_update_points(
                    ITEMS_COLLECTION, update_operations=operations, wait=True
                )
                updated += len(operations)
            if offset is None:
                return updated
