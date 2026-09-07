"""Recording a run request and moving it through its lifecycle.

The app records a request and stops there. The orchestrator picks it up. That
split is what lets a request survive the orchestrator being down, and it is why
the job — not the sensor — owns the move to running.
"""

import pytest

from phases_v2.requests.domain import (
    finish,
    mark_failed,
    start,
    submit,
)
from phases_v2.requests.fakes import FakeRequestStore
from phases_v2.requests.interfaces import (
    FAILED,
    PENDING,
    RUNNING,
    SUCCEEDED,
    InvalidTransition,
)


def _submit(store, **kwargs):
    params = dict(
        locations=["papers"],
        chunker_id="window_1_abc",
        prompt_id="claims_abc",
        model_id="openai/gpt-4.1-mini",
    )
    params.update(kwargs)
    return submit(store, **params)


def test_a_submitted_request_is_recorded_pending_with_its_inputs():
    store = FakeRequestStore()

    request = _submit(store, requested_by="maxime")

    assert request.status == PENDING
    assert request.request_id
    assert request.locations == ["papers"]
    assert request.chunker_id == "window_1_abc"
    assert request.prompt_id == "claims_abc"
    assert request.model_id == "openai/gpt-4.1-mini"
    assert request.requested_by == "maxime"
    assert request.requested_at is not None
    assert store.get(request.request_id) == request


def test_every_submission_gets_its_own_id():
    store = FakeRequestStore()

    first, second = _submit(store), _submit(store)

    assert first.request_id != second.request_id


def test_a_request_missing_a_required_input_is_refused():
    store = FakeRequestStore()

    for missing in ("chunker_id", "prompt_id", "model_id"):
        with pytest.raises(ValueError, match=missing):
            _submit(store, **{missing: ""})

    assert store.requests == {}


def test_a_request_with_no_locations_is_refused_and_says_so():
    store = FakeRequestStore()

    with pytest.raises(ValueError, match="locations"):
        _submit(store, locations=[])


def test_a_store_that_cannot_record_the_request_reports_rather_than_pretends():
    store = FakeRequestStore(broken=True)

    with pytest.raises(RuntimeError):
        _submit(store)


def test_pending_requests_are_what_the_orchestrator_sees():
    store = FakeRequestStore()
    first = _submit(store)
    second = _submit(store)
    start(store, first.request_id, run_id="run-1")

    assert [r.request_id for r in store.pending()] == [second.request_id]


def test_starting_a_request_moves_it_to_running_and_records_the_run():
    store = FakeRequestStore()
    request = _submit(store)

    started = start(store, request.request_id, run_id="run-1")

    assert started.status == RUNNING
    assert started.run_id == "run-1"
    assert started.started_at is not None


def test_a_request_cannot_be_started_twice():
    # The job owns this transition, so a second start means two runs took the
    # same request — which is exactly what must not happen silently.
    store = FakeRequestStore()
    request = _submit(store)
    start(store, request.request_id, run_id="run-1")

    with pytest.raises(InvalidTransition):
        start(store, request.request_id, run_id="run-2")


def test_finishing_a_running_request_records_the_outcome():
    store = FakeRequestStore()
    request = _submit(store)
    start(store, request.request_id, run_id="run-1")

    finished = finish(store, request.request_id)

    assert finished.status == SUCCEEDED
    assert finished.finished_at is not None
    assert finished.error is None


def test_a_failed_run_records_the_reason_and_is_not_pending_again():
    store = FakeRequestStore()
    request = _submit(store)
    start(store, request.request_id, run_id="run-1")

    failed = mark_failed(store, request.request_id, "model quota exhausted")

    assert failed.status == FAILED
    assert failed.error == "model quota exhausted"
    assert store.pending() == []


def test_a_pending_request_can_fail_without_ever_running():
    store = FakeRequestStore()
    request = _submit(store)

    failed = mark_failed(store, request.request_id, "config rejected")

    assert failed.status == FAILED


def test_a_finished_request_cannot_be_finished_again():
    store = FakeRequestStore()
    request = _submit(store)
    start(store, request.request_id, run_id="run-1")
    finish(store, request.request_id)

    with pytest.raises(InvalidTransition):
        finish(store, request.request_id)


def test_an_unknown_request_cannot_be_transitioned():
    from phases_v2.requests.interfaces import RequestNotFound

    store = FakeRequestStore()

    with pytest.raises(RequestNotFound):
        start(store, "nope", run_id="run-1")
