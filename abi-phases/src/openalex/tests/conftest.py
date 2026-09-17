import pytest
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService


@pytest.fixture
def dataset(tmp_path):
    return DatasetService(
        DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path}/catalog.sqlite", data_path=f"{tmp_path}/data/"
        )
    )
