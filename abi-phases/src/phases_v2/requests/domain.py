"""Recording a run request and moving it through its lifecycle.

The app's whole responsibility is :func:`submit`. It never contacts the
orchestrator, so a request made while the orchestrator is down is simply picked
up when it returns.

The transitions are guarded because they encode who owns what. A sensor may
observe a pending request many times, but only the job it starts calls
:func:`start` — so a second start means two runs took the same request, which
must fail loudly rather than quietly double the work.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from phases_v2.requests.interfaces import (
    FAILED,
    PENDING,
    RUNNING,
    SUCCEEDED,
    TERMINAL,
    InvalidTransition,
    RequestStore,
    RunRequest,
)


def submit(
    store: RequestStore,
    *,
    locations: list[str],
    chunker_id: str,
    prompt_id: str,
    model_id: str,
    requested_by: str | None = None,
) -> RunRequest:
    """Record a pending request. Returns it, including its ``request_id``.

    Validation happens before the write, so a request missing an input is
    refused rather than left pending and unrunnable.
    """
    if not locations:
        raise ValueError(
            "a run needs locations: at least one storage location to ingest from"
        )
    for name, value in (
        ("chunker_id", chunker_id),
        ("prompt_id", prompt_id),
        ("model_id", model_id),
    ):
        if not value:
            raise ValueError(f"a run needs a {name}")

    request = RunRequest(
        request_id=str(uuid.uuid4()),
        status=PENDING,
        locations=list(locations),
        chunker_id=chunker_id,
        prompt_id=prompt_id,
        model_id=model_id,
        requested_by=requested_by,
        requested_at=datetime.now(UTC),
    )
    store.save(request)
    return request


def start(store: RequestStore, request_id: str, *, run_id: str) -> RunRequest:
    """Move a pending request to running. Called by the job, not the sensor."""
    request = store.get(request_id)
    if request.status != PENDING:
        raise InvalidTransition(
            f"request {request_id} is {request.status}, so it cannot be started"
        )
    updated = _replace(request, status=RUNNING, run_id=run_id, started_at=_now())
    store.save(updated)
    return updated


def finish(store: RequestStore, request_id: str) -> RunRequest:
    request = store.get(request_id)
    if request.status in TERMINAL:
        raise InvalidTransition(
            f"request {request_id} already finished as {request.status}"
        )
    updated = _replace(request, status=SUCCEEDED, finished_at=_now())
    store.save(updated)
    return updated


def mark_failed(store: RequestStore, request_id: str, error: str) -> RunRequest:
    """Record a failure. A failed request is never pending again.

    Retrying is a new request: silently re-queueing this one would make a
    permanently broken configuration loop forever.
    """
    request = store.get(request_id)
    if request.status in TERMINAL:
        raise InvalidTransition(
            f"request {request_id} already finished as {request.status}"
        )
    updated = _replace(request, status=FAILED, error=error, finished_at=_now())
    store.save(updated)
    return updated


def _now() -> datetime:
    return datetime.now(UTC)


def _replace(request: RunRequest, **changes) -> RunRequest:
    from dataclasses import replace

    return replace(request, **changes)
