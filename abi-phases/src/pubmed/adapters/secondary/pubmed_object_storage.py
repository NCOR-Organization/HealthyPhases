"""Translate storage failures at the application boundary."""

from naas_abi_core.services.object_storage.ObjectStoragePort import Exceptions

from pubmed.domain.pubmed_errors import AcquisitionError


class PubmedObjectStorage:
    def __init__(self, storage):
        self.storage = storage

    def get_object(self, prefix, key):
        try:
            return self.storage.get_object(prefix, key)
        except Exceptions.ObjectNotFound as exc:
            raise FileNotFoundError(key) from exc

    def put_object(self, prefix, key, content):
        try:
            self.storage.put_object(prefix, key, content)
        except Exception as exc:
            raise AcquisitionError("Could not store the downloaded PDF") from exc
