from concurrent.futures import ThreadPoolExecutor

import pytest
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from pubmed.adapters.secondary.pubmed_dataset_store import PubmedDatasetStore
from pubmed.application.pubmed_service import PubmedService
from pubmed.domain.pubmed_errors import RequestAlreadyClaimed
from pubmed.tests.pubmed_service_test import FakeSource, MemoryStorage, queue


@pytest.fixture
def dataset(tmp_path):
    return DatasetService(
        DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path}/catalog.sqlite",
            data_path=f"{tmp_path}/data/",
        )
    )


def test_real_dataset_publication_roundtrip_and_idempotent_startup(dataset):
    store = PubmedDatasetStore(dataset)
    store.ensure()
    publisher = PubmedService(store, FakeSource(), MemoryStorage())
    row = queue(publisher)
    result = publisher.execute(row["request_id"], "dagster-run")
    assert result["status"] == "succeeded"
    assert len(store.rows("artifacts")) == 2
    assert isinstance(store.rows("artifacts")[0]["size_bytes"], int)
    store.ensure()
    assert len(store.rows("artifacts")) == 2
    assert publisher.requests()[0]["outcomes"]["1"]["status"] == "ready"


def test_concurrent_claims_have_one_owner(dataset):
    store = PubmedDatasetStore(dataset)
    store.ensure()
    row = queue(PubmedService(store, FakeSource(), MemoryStorage()))

    def claim(run):
        try:
            return store.claim(row["request_id"], run)["run_id"]
        except RequestAlreadyClaimed:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["one", "two"]))
    assert sum(result is not None for result in results) == 1
