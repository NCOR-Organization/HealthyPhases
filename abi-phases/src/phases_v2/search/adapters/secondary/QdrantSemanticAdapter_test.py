from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from naas_abi_core.services.vector_store.adapters.QdrantAdapter import QdrantAdapter
from naas_abi_core.services.vector_store.VectorStoreService import VectorStoreService
from qdrant_client import QdrantClient

from phases_v2.projection.adapters.secondary.QdrantMetadataSink import (
    QdrantMetadataSink,
)
from phases_v2.projection.adapters.secondary.VectorStoreSink import VectorStoreSink
from phases_v2.projection.interfaces import VectorDoc
from phases_v2.projection.metadata import search_metadata
from phases_v2.projection.vectors import ITEMS_COLLECTION
from phases_v2.search.adapters.secondary.QdrantSemanticAdapter import (
    QdrantSemanticAdapter,
)
from phases_v2.search.domain import SearchService
from phases_v2.search.fakes import FakeExtractedItems, FakeItem, FakeSemanticIndex
from phases_v2.search.models import ItemLocation


def seed(client, count=523, legacy=False):
    port = QdrantAdapter()
    port.client = client
    store = VectorStoreService(port)
    sink = VectorStoreSink(store)
    sink.ensure_collection(ITEMS_COLLECTION, 2)
    docs = []
    metadata = {}
    for i in range(count):
        item = {
            "item_id": str(i),
            "extraction_id": "e",
            "chunk_id": "c",
            "paper_id": "p",
            "prompt_id": "pr",
        }
        values = search_metadata(
            item,
            {"model_id": "model-a"},
            {"storage_prefix": "papers", "storage_key": "stress/doc.pdf"},
            {"name": "prompt-a"},
        )
        metadata[str(i)] = values
        docs.append(VectorDoc(str(i), "claim", {} if legacy else values))
    sink.store(ITEMS_COLLECTION, docs, [[1.0, 0.0]] * count)
    return metadata


def test_native_pages_filter_count_and_export_without_full_ranking():
    with closing(QdrantClient(":memory:")) as client:
        seed(client)
        embedder = SimpleNamespace(embed=Mock(return_value=[[1.0, 0.0]]))
        native = QdrantSemanticAdapter(client, embedder)
        client.query_points = Mock(wraps=client.query_points)
        legacy = FakeSemanticIndex()
        legacy.search_all = Mock(side_effect=AssertionError("legacy search used"))
        items = FakeExtractedItems(
            [FakeItem(str(i), "claim", ItemLocation()) for i in range(523)]
        )
        items.matching_item_ids = Mock(
            side_effect=AssertionError("dataset filtering used")
        )
        service = SearchService(legacy, items, native_index=native)
        filters = {
            "prompts": ["prompt-a", "other"],
            "models": ["model-a"],
            "paths": ["/papers/"],
        }
        first, total = service.page("semantic", "claim", limit=10, **filters)
        second, _ = service.page("semantic", "claim", limit=10, offset=10, **filters)
        assert total == 523 and len(first) == len(second) == 10
        assert not {h.item_id for h in first} & {h.item_id for h in second}
        assert [c.kwargs["limit"] for c in client.query_points.call_args_list] == [
            10,
            10,
        ]
        assert all(
            c.kwargs["query_filter"] is not None
            for c in client.query_points.call_args_list
        )
        assert embedder.embed.call_count == 1
        exported = list(service.all_hits("semantic", "claim", **filters))
        assert len(exported) == len({h.item_id for h in exported}) == 523
        assert native.page("claim", 10, 0, paths=["papers/stress-other"])[1] == 0
        assert native.page("claim", 10, 0, prompts=["missing"])[1] == 0
        assert native.page("claim", 10, 0, models=["missing"])[1] == 0
        assert native.page("claim", 10, 600)[0] == []


def test_threshold_enumerates_only_ids_and_scores_once():
    with closing(QdrantClient(":memory:")) as client:
        seed(client, 1100)
        native = QdrantSemanticAdapter(
            client, SimpleNamespace(embed=lambda texts: [[1.0, 0.0]])
        )
        client.query_points = Mock(wraps=client.query_points)
        hits, total = native.page(
            "claim", 10, 0, score_threshold=0.8, prompts=["prompt-a"]
        )
        assert len(hits) == 10 and total == 1100
        assert len(client.query_points.call_args_list) == 2
        assert all(
            c.kwargs["with_payload"] is False and c.kwargs["score_threshold"] == 0.8
            for c in client.query_points.call_args_list
        )
        native.page("claim", 10, 10, score_threshold=0.8, prompts=["prompt-a"])
        assert len(client.query_points.call_args_list) == 2
        assert native.page("claim", 10, 0, score_threshold=1.1)[1] == 0


def test_metadata_refresh_preserves_ids_vectors_and_text():
    with closing(QdrantClient(":memory:")) as client:
        metadata = seed(client, 3, legacy=True)
        native = QdrantSemanticAdapter(
            client, SimpleNamespace(embed=lambda texts: [[1.0, 0.0]])
        )
        assert not native.ready()
        before, _ = client.scroll(
            ITEMS_COLLECTION, with_vectors=True, with_payload=True
        )
        assert QdrantMetadataSink(client).refresh(metadata) == 3
        after, _ = client.scroll(ITEMS_COLLECTION, with_vectors=True, with_payload=True)
        assert [(p.id, p.vector, p.payload["payload"]) for p in before] == [
            (p.id, p.vector, p.payload["payload"]) for p in after
        ]
        assert QdrantSemanticAdapter(client, native._embedder).ready()
        assert all(
            p.payload["source_ancestors"] == ["papers", "papers/stress"] for p in after
        )
        assert QdrantMetadataSink(client).refresh(metadata) == 3


def test_metadata_refresh_fails_on_unknown_points():
    with closing(QdrantClient(":memory:")) as client:
        seed(client, 1, legacy=True)
        with pytest.raises(ValueError, match="No dataset metadata"):
            QdrantMetadataSink(client).refresh({})
        assert not QdrantSemanticAdapter(client, None).ready()
