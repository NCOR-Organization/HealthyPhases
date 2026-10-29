"""Only manifest objects can be read, and each must match its known checksum.

A collection's folder documents nothing has read yet have no checksum in the
manifest; they are read as listed, and ingestion identifies them by content.
"""

from hashlib import sha256

from phases_v2.papers.interfaces import ObjectNotFound


class ManifestSource:
    def __init__(self, storage, artifacts):
        self.storage = storage
        self.artifacts = {(a["storage_prefix"], a["storage_key"]): a for a in artifacts}

    def list_objects_recursive(self, prefix):
        return [key for location, key in self.artifacts if location == prefix]

    def get_object(self, prefix, key):
        artifact = self.artifacts.get((prefix, key))
        if artifact is None:
            raise ObjectNotFound("Object is not in the submitted manifest")
        content = self.storage.get_object(prefix, key)
        expected = artifact.get("content_sha256")
        if expected and sha256(content).hexdigest() != expected:
            raise ValueError(
                f"{prefix}/{key} changed after this run was requested: its content "
                "no longer matches the checksum the run was given. Request the run "
                "again to read the current file."
            )
        return content

    def put_object(self, prefix, key, content):
        self.storage.put_object(prefix, key, content)
