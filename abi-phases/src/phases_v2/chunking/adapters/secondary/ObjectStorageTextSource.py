"""Rendered paper text, read back from object storage."""

from __future__ import annotations

from naas_abi_core.services.object_storage.ObjectStorageService import (
    ObjectStorageService,
)

from phases_v2.papers.domain import TEXT_PREFIX


class ObjectStorageTextSource:
    def __init__(self, storage: ObjectStorageService, prefix: str = TEXT_PREFIX):
        self._storage = storage
        self._prefix = prefix

    def read_text(self, text_key: str) -> str:
        return self._storage.get_object(self._prefix, text_key).decode("utf-8")
