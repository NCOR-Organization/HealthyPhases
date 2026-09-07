"""The engine's object storage, as the domain's :class:`ObjectSource`.

Its only real work is translating the platform's not-found error into the
domain's, so the domain can treat a missing location as a reportable failure
without importing anything from the platform.
"""

from __future__ import annotations

from naas_abi_core.services.object_storage.ObjectStoragePort import (
    Exceptions as StorageExceptions,
)
from naas_abi_core.services.object_storage.ObjectStorageService import (
    ObjectStorageService,
)

from phases_v2.papers.interfaces import ObjectNotFound


class ObjectStorageSource:
    def __init__(self, storage: ObjectStorageService):
        self._storage = storage

    def list_objects_recursive(self, prefix: str) -> list[str]:
        try:
            keys = self._storage.list_objects_recursive(prefix)
        except StorageExceptions.ObjectNotFound as missing:
            raise ObjectNotFound(str(missing)) from missing
        # The service returns keys relative to the storage root; the domain
        # wants them relative to the location it asked about.
        trimmed = prefix.rstrip("/") + "/"
        return [
            key[len(trimmed):] if key.startswith(trimmed) else key for key in keys
        ]

    def get_object(self, prefix: str, key: str) -> bytes:
        return self._storage.get_object(prefix, key)

    def put_object(self, prefix: str, key: str, content: bytes) -> None:
        self._storage.put_object(prefix, key, content)
