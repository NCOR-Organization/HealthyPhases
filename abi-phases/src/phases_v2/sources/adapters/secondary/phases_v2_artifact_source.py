"""Only manifest objects can be read, and each must match its published checksum."""

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
        if sha256(content).hexdigest() != artifact["content_sha256"]:
            raise ValueError(f"Published artifact checksum mismatch: {prefix}/{key}")
        return content

    def put_object(self, prefix, key, content):
        self.storage.put_object(prefix, key, content)
