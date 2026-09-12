"""Bounded, process-local reuse of snapshot-scoped search computations."""

from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import fields, is_dataclass
from sys import getsizeof
from threading import Lock
from time import monotonic


def _size(value):
    size = getsizeof(value)
    if isinstance(value, tuple):
        size += sum(_size(item) for item in value)
    elif is_dataclass(value):
        size += sum(_size(getattr(value, f.name)) for f in fields(value))
    return size


class SearchResultCache:
    def __init__(
        self, max_bytes=64 * 1024 * 1024, max_entries=32, ttl=300, clock=monotonic
    ):
        self._max_bytes = max_bytes
        self._max_entries = max_entries
        self._ttl = ttl
        self._clock = clock
        self._entries = OrderedDict()
        self._pending = {}
        self._bytes = 0
        self._lock = Lock()

    def get_or_compute(self, key, compute):
        with self._lock:
            now = self._clock()
            for expired in [
                k for k, (_, deadline, _) in self._entries.items() if deadline <= now
            ]:
                self._bytes -= self._entries.pop(expired)[2]
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key][0]
            future = self._pending.get(key)
            owner = future is None
            if owner:
                future = self._pending[key] = Future()
        if not owner:
            return future.result()
        try:
            value = compute()
            size = _size(value) + _size(key)
            with self._lock:
                if size <= self._max_bytes and self._max_entries > 0:
                    while self._entries and (
                        self._bytes + size > self._max_bytes
                        or len(self._entries) >= self._max_entries
                    ):
                        self._bytes -= self._entries.popitem(last=False)[1][2]
                    self._entries[key] = (value, self._clock() + self._ttl, size)
                    self._bytes += size
            future.set_result(value)
            return value
        except BaseException as error:
            future.set_exception(error)
            raise
        finally:
            with self._lock:
                self._pending.pop(key, None)
