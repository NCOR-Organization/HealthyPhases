"""Module load must survive a deployment with no dataset service.

Every process that starts the engine runs this — API, Dagster daemon, each run
worker — so it has to be repeatable, and it must never be the reason the engine
fails to boot.
"""

from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

import phases_v2
from phases_v2.datasets.schemas import DATASETS, NAMESPACE
from phases_v2.fakes import InMemoryRowStore


class _Services:
    def __init__(self, dataset: DatasetService | None):
        self._dataset = dataset

    def dataset_available(self) -> bool:
        return self._dataset is not None

    @property
    def dataset(self) -> DatasetService:
        assert self._dataset is not None
        return self._dataset


class _Engine:
    def __init__(self, dataset: DatasetService | None):
        self.services = _Services(dataset)


def _dataset(tmp_path) -> DatasetService:
    return DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path / 'catalog.sqlite'}",
            data_path=str(tmp_path / "data") + "/",
        )
    )


def test_datasets_are_created_when_the_service_is_available(tmp_path):
    dataset = _dataset(tmp_path)

    created = phases_v2.ensure_datasets_if_available(_Engine(dataset))

    assert created == {spec.name for spec in DATASETS}
    assert {info.name for info in dataset.list(namespace=NAMESPACE)} == created


def test_loading_twice_creates_nothing_the_second_time(tmp_path):
    dataset = _dataset(tmp_path)
    engine = _Engine(dataset)

    phases_v2.ensure_datasets_if_available(engine)
    created = phases_v2.ensure_datasets_if_available(engine)

    assert created == set()


def test_a_deployment_without_a_dataset_service_still_loads():
    created = phases_v2.ensure_datasets_if_available(_Engine(None))

    assert created == set()


def test_the_absent_service_is_reported_rather_than_passed_over_silently():
    # naas_abi_core logs through loguru, so neither caplog (stdlib logging) nor
    # capsys/capfd reliably observe it. Attaching a sink asks loguru directly
    # instead of guessing where the bytes went.
    from naas_abi_core import logger

    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        phases_v2.ensure_datasets_if_available(_Engine(None))
    finally:
        logger.remove(sink_id)

    assert any("phases_v2" in message for message in messages), messages
    assert any("dataset" in message.lower() for message in messages), messages


def test_declarations_are_published_on_load():
    store = InMemoryRowStore()

    published = phases_v2.register_declarations(store)

    assert published["prompts"] and published["chunkers"] and published["models"]
    assert store.count("prompts") == len(published["prompts"])
    assert store.count("chunkers") == len(published["chunkers"])
    assert store.count("models") == len(published["models"])


def test_loading_twice_leaves_exactly_one_row_per_declaration():
    store = InMemoryRowStore()

    first = phases_v2.register_declarations(store)
    phases_v2.register_declarations(store)

    assert store.count("prompts") == len(first["prompts"])
    assert store.count("chunkers") == len(first["chunkers"])
    assert store.count("models") == len(first["models"])


def test_registration_never_reads_before_writing():
    # Upsert makes a read unnecessary, and the fake proves it: its query()
    # raises, so a registry that looked first would fail here rather than
    # quietly costing a round trip on every engine start in every process.
    store = InMemoryRowStore()

    phases_v2.register_declarations(store)

    assert store.writes == ["prompts", "chunkers", "models"]


def test_declarations_reach_the_real_store_through_module_load(tmp_path):
    dataset = _dataset(tmp_path)

    published = phases_v2.load_module_declarations(_Engine(dataset))

    rows = dataset.query(
        "SELECT prompt_id FROM prompts", namespace=NAMESPACE
    ).rows
    assert {row["prompt_id"] for row in rows} == set(published["prompts"])


def test_module_load_without_a_dataset_service_publishes_nothing():
    assert phases_v2.load_module_declarations(_Engine(None)) == {}
