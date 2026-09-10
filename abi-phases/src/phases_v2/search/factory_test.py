"""Reverse search, wired against the real dataset.

The semantic half is substituted with a fake — a real embedder needs an API
key — so this exercises the wiring and the extracted-items half against a real
dataset, the same split ``projection.factory_test`` uses for the embedder.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2 import PhasesV2Configuration
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.store import ensure_datasets
from phases_v2.search.adapters.secondary.VectorStoreSemanticAdapter import (
    VectorStoreSemanticAdapter,
)
from phases_v2.search.factory import search_service
from phases_v2.search.fakes import FakeItem, FakeSemanticIndex
from phases_v2.search.models import ItemLocation


class _Services:
    def __init__(self, dataset):
        self.dataset = dataset
        self.vector_store = None  # never touched: semantic_index is overridden


class _Engine:
    def __init__(self, dataset):
        self.services = _Services(dataset)
        self.modules = {
            "phases_v2": SimpleNamespace(
                configuration=PhasesV2Configuration(
                    global_config={"ai_mode": "cloud"}, openai_api_key="configured-test-key"
                )
            )
        }


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
    rows.write_rows("papers", [{"paper_id": "p0", "file_name": "a.pdf"}])
    rows.write_rows(
        "prompts", [{"prompt_id": "pr0", "name": "solitude_effects", "output_key": "effects"}]
    )
    rows.write_rows(
        "chunks",
        [{"chunk_id": "c0", "paper_id": "p0", "chunker_id": "w1", "seq": 0, "text": "chunk 0"}],
    )
    rows.write_rows(
        "extractions",
        [
            {
                "extraction_id": "e0", "chunk_id": "c0", "model_id": "m0",
                "prompt_id": "pr0", "run_id": "r0", "status": "succeeded",
            }
        ],
    )
    rows.write_rows(
        "extracted_items",
        [
            {
                "item_id": "i0", "extraction_id": "e0", "chunk_id": "c0",
                "paper_id": "p0", "prompt_id": "pr0", "seq": 0,
                "text": "solitude reduces stress",
            }
        ],
    )
    return _Engine(dataset)


def test_the_default_semantic_index_is_the_vector_store_adapter(engine):
    service = search_service(engine)

    assert isinstance(service._index, VectorStoreSemanticAdapter)


def test_api_proxy_uses_explicit_module_configuration(engine, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    configuration = engine.modules["phases_v2"].configuration
    del engine.modules
    service = search_service(engine, configuration=configuration)
    assert service._index._embedder._api_key == "configured-test-key"


def test_keyword_search_and_facets_run_against_the_real_dataset(engine):
    fake = FakeSemanticIndex([FakeItem("i0", "solitude reduces stress", ItemLocation())])
    service = search_service(engine, semantic_index=fake)

    hits = service.keyword_search("solitude stress")

    assert [h.item_id for h in hits] == ["i0"]
    assert hits[0].paper_name == "a.pdf"
    assert hits[0].prompt_name == "solitude_effects"
    assert service.list_prompts() == ["solitude_effects"]
