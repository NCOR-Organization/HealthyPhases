"""Vector projection against the real sqlite-vec store.

The embedder is faked — real embeddings cost money and need a key — but the
vector store is the configured one, which is where the upsert-by-id behaviour
this design leans on actually lives.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService
from naas_abi_core.services.vector_store.adapters.SqliteVecAdapter import (
    SqliteVecAdapter,
)
from naas_abi_core.services.vector_store.VectorStoreService import VectorStoreService

from phases_v2 import PhasesV2Configuration
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.store import ensure_datasets
from phases_v2.projection.adapters.secondary.OpenAIEmbedder import OpenAIEmbedder
from phases_v2.projection.adapters.secondary.VectorStoreSink import VectorStoreSink
from phases_v2.projection.factory import project_to_vectors
from phases_v2.projection.fakes import FakeEmbedder
from phases_v2.projection.vectors import CHUNKS_COLLECTION, ITEMS_COLLECTION


class _Services:
    def __init__(self, dataset, vector_store):
        self.dataset = dataset
        self.vector_store = vector_store

    def dataset_available(self) -> bool:
        return True


class _Engine:
    def __init__(self, dataset, vector_store):
        self.services = _Services(dataset, vector_store)


@pytest.fixture
def engine(tmp_path):
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path / 'catalog.sqlite'}",
            data_path=str(tmp_path / "warehouse") + "/",
        )
    )
    ensure_datasets(dataset)
    rows = DatasetRowStore(dataset)
    now = datetime.now(UTC)
    rows.write_rows(
        "chunks",
        [{"chunk_id": f"c{i}", "paper_id": "p0", "chunker_id": "w1", "seq": i,
          "text": f"chunk {i}"} for i in range(3)],
    )
    rows.write_rows(
        "extracted_items",
        [{"item_id": f"i{i}", "extraction_id": f"e{i}", "chunk_id": f"c{i}",
          "paper_id": "p0", "prompt_id": "pr", "seq": 0, "text": f"claim {i}"}
         for i in range(3)],
    )
    rows.write_rows(
        "extractions",
        [{"extraction_id": f"e{i}", "chunk_id": f"c{i}", "model_id": "m",
          "prompt_id": "pr", "run_id": "r", "status": "succeeded",
          "response": {"results": [f"claim {i}"]}, "raw_response": "{}",
          "item_count": 1, "completed_at": now} for i in range(3)],
    )
    # Wrapped in the service, because that is what the engine hands the module.
    # An earlier version passed the bare adapter here, which is precisely why
    # the sink calling adapter-only methods passed its tests and failed in a
    # real run.
    store = VectorStoreService(
        adapter=SqliteVecAdapter(persistence_path=str(tmp_path / "vectors.sqlite3"))
    )
    store.initialize()
    return _Engine(dataset, store)


def _run(engine, embedder):
    return project_to_vectors(
        engine, sink=VectorStoreSink(engine.services.vector_store), embedder=embedder
    )


def test_chunks_and_items_are_embedded_into_their_own_collections(engine):
    embedder = FakeEmbedder()

    report = _run(engine, embedder)

    assert report.projected == 6
    store = engine.services.vector_store
    assert store.get_collection_size(CHUNKS_COLLECTION) == 3
    assert store.get_collection_size(ITEMS_COLLECTION) == 3


def test_default_projection_embedder_uses_module_credentials(engine, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    engine.modules = {
        "phases_v2": SimpleNamespace(configuration=PhasesV2Configuration(
            global_config={"ai_mode": "cloud"}, openai_api_key="projection-test-key"
        ))
    }

    def embed(self, texts):
        assert self._api_key == "projection-test-key"
        return [[1.0] + [0.0] * (self.dimension - 1) for _ in texts]

    monkeypatch.setattr(OpenAIEmbedder, "embed", embed)
    assert project_to_vectors(engine).projected == 6


def test_a_second_run_computes_no_embeddings_and_stores_nothing_new(engine):
    _run(engine, FakeEmbedder())
    store = engine.services.vector_store
    before = (
        store.get_collection_size(CHUNKS_COLLECTION),
        store.get_collection_size(ITEMS_COLLECTION),
    )
    embedder = FakeEmbedder()

    report = _run(engine, embedder)

    assert embedder.embedded == []
    assert report.projected == 0
    assert (
        store.get_collection_size(CHUNKS_COLLECTION),
        store.get_collection_size(ITEMS_COLLECTION),
    ) == before


def test_provenance_survives_the_round_trip(engine):
    _run(engine, FakeEmbedder())

    import numpy as np

    store = engine.services.vector_store
    hits = store.search_similar(
        ITEMS_COLLECTION, np.asarray(FakeEmbedder().embed(["claim 0"])[0]), k=3
    )
    hit = next(hit for hit in hits if hit.metadata["item_id"] == "i0")
    stored = store.get_document(ITEMS_COLLECTION, hit.id)

    assert stored is not None
    assert stored.metadata["document_id"] == "i0"
    assert stored.metadata["chunk_id"] == "c0"
    assert stored.metadata["paper_id"] == "p0"
    assert stored.metadata["model_id"] == "m"
    assert stored.metadata["prompt_id"] == "pr"


def test_re_storing_the_same_id_replaces_rather_than_duplicates(engine):
    # The whole incremental design rests on this being an upsert.
    _run(engine, FakeEmbedder())
    store = engine.services.vector_store
    before = store.get_collection_size(ITEMS_COLLECTION)

    sink = VectorStoreSink(store)
    doc, vector = _first_doc_and_vector()
    sink.store(ITEMS_COLLECTION, [doc], [vector])

    assert store.get_collection_size(ITEMS_COLLECTION) == before


def _first_doc_and_vector():
    from phases_v2.projection.interfaces import VectorDoc

    return (
        VectorDoc(id="i0", text="claim 0 rewritten", metadata={"chunk_id": "c0"}),
        [0.5] * FakeEmbedder().dimension,
    )
