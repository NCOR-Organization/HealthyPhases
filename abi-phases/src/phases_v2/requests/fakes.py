"""In-memory double for the run-request domain tests."""

from __future__ import annotations

from phases_v2.requests.interfaces import (
    PENDING,
    RequestNotFound,
    RunRequest,
)


class FakeRequestStore:
    def __init__(self, broken: bool = False):
        self.requests: dict[str, RunRequest] = {}
        self._broken = broken

    def save(self, request: RunRequest) -> None:
        if self._broken:
            raise RuntimeError("request store unreachable")
        self.requests[request.request_id] = request

    def get(self, request_id: str) -> RunRequest:
        try:
            return self.requests[request_id]
        except KeyError as missing:
            raise RequestNotFound(request_id) from missing

    def pending(self) -> list[RunRequest]:
        return [r for r in self.requests.values() if r.status == PENDING]

    def recent(self, limit: int = 50) -> list[RunRequest]:
        return list(self.requests.values())[:limit]
