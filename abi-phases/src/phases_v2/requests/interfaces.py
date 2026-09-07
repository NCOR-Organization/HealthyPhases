"""What run requests need, stated without naming a store or an orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"

TERMINAL = (SUCCEEDED, FAILED)


class RequestNotFound(Exception):
    pass


class InvalidTransition(Exception):
    """A request was moved to a state it cannot reach from where it is."""


@dataclass(frozen=True)
class RunRequest:
    request_id: str
    status: str
    locations: list[str]
    chunker_id: str
    prompt_id: str
    model_id: str
    requested_by: str | None = None
    requested_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    run_id: str | None = None
    error: str | None = None


class RequestStore(Protocol):
    def save(self, request: RunRequest) -> None: ...

    def get(self, request_id: str) -> RunRequest: ...

    def pending(self) -> list[RunRequest]: ...

    def recent(self, limit: int = 50) -> list[RunRequest]: ...
