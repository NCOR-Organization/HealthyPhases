"""Run requests against the real dataset."""

import pytest
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2.datasets.store import ensure_datasets
from phases_v2.requests.domain import finish, mark_failed, start, submit
from phases_v2.requests.factory import request_store
from phases_v2.requests.interfaces import FAILED, PENDING, RUNNING, SUCCEEDED


class _Services:
    def __init__(self, dataset):
        self.dataset = dataset

    def dataset_available(self) -> bool:
        return True


class _Engine:
    def __init__(self, dataset):
        self.services = _Services(dataset)


@pytest.fixture
def store(tmp_path):
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path / 'catalog.sqlite'}",
            data_path=str(tmp_path / "warehouse") + "/",
        )
    )
    ensure_datasets(dataset)
    return request_store(_Engine(dataset))


def _submit(store):
    return submit(
        store,
        locations=["papers", "archive"],
        chunker_id="window_1_abc",
        prompt_ids=["claims_abc"],
        model_id="openai/gpt-4.1-mini",
        requested_by="maxime",
    )


def test_a_request_round_trips_including_its_locations(store):
    request = _submit(store)

    loaded = store.get(request.request_id)

    assert loaded.status == PENDING
    assert loaded.locations == ["papers", "archive"]
    assert loaded.requested_by == "maxime"
    assert loaded.requested_at is not None


def test_pending_lists_only_what_has_not_started(store):
    first = _submit(store)
    second = _submit(store)
    start(store, first.request_id, run_id="run-1")

    assert [r.request_id for r in store.pending()] == [second.request_id]


def test_the_lifecycle_is_persisted_not_just_returned(store):
    request = _submit(store)

    start(store, request.request_id, run_id="run-1")
    assert store.get(request.request_id).status == RUNNING

    finish(store, request.request_id)
    loaded = store.get(request.request_id)
    assert loaded.status == SUCCEEDED
    assert loaded.run_id == "run-1"
    assert loaded.finished_at is not None


def test_a_failure_is_persisted_with_its_reason(store):
    request = _submit(store)
    start(store, request.request_id, run_id="run-1")

    mark_failed(store, request.request_id, "quota exhausted")

    loaded = store.get(request.request_id)
    assert loaded.status == FAILED
    assert loaded.error == "quota exhausted"
    assert store.pending() == []


def test_transitions_leave_one_row_not_a_history(store):
    request = _submit(store)
    start(store, request.request_id, run_id="run-1")
    finish(store, request.request_id)

    assert len(store.recent()) == 1


def test_a_hostile_request_id_cannot_break_the_lookup(store):
    from phases_v2.requests.interfaces import RequestNotFound

    with pytest.raises(RequestNotFound):
        store.get("x' OR '1'='1")
