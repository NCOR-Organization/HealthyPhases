"""In-memory doubles for the paper-ingestion domain tests."""

from __future__ import annotations

from phases_v2.papers.interfaces import (
    ObjectNotFound,
    PaperRecord,
    RenderFailed,
)


class FakeObjectSource:
    """An object store as a flat dict of ``(prefix, key) -> bytes``."""

    def __init__(self, objects: dict[tuple[str, str], bytes] | None = None):
        self._objects: dict[tuple[str, str], bytes] = dict(objects or {})
        self.reads: list[tuple[str, str]] = []
        self.writes: list[tuple[str, str]] = []

    def add(self, prefix: str, key: str, content: bytes) -> None:
        self._objects[(prefix, key)] = content

    def list_objects_recursive(self, prefix: str) -> list[str]:
        keys = sorted(k for (p, k) in self._objects if p == prefix)
        if not keys:
            raise ObjectNotFound(f"{prefix} not found")
        return keys

    def get_object(self, prefix: str, key: str) -> bytes:
        self.reads.append((prefix, key))
        return self._objects[(prefix, key)]

    def put_object(self, prefix: str, key: str, content: bytes) -> None:
        self.writes.append((prefix, key))
        self._objects[(prefix, key)] = content


class FakeTextRenderer:
    """Renders bytes to text, and can be told to fail for specific names."""

    def __init__(
        self,
        unreadable: set[str] | None = None,
        suffixes: tuple[str, ...] | None = None,
    ):
        self._unreadable = unreadable or set()
        self._suffixes = suffixes
        self.rendered: list[str] = []

    def handles(self, file_name: str) -> bool:
        if self._suffixes is None:
            return True
        return file_name.lower().endswith(self._suffixes)

    def render(self, content: bytes, file_name: str) -> str:
        if file_name in self._unreadable:
            raise RenderFailed(f"cannot read {file_name}")
        self.rendered.append(file_name)
        return f"text of {file_name}: {content.decode('utf-8', 'replace')}"


class FakePaperStore:
    def __init__(self) -> None:
        self.papers: dict[str, PaperRecord] = {}
        self.reads = 0

    def already_ingested(self) -> dict[str, str | None]:
        self.reads += 1
        return {
            paper_id: record.text_key for paper_id, record in self.papers.items()
        }

    def save(self, papers: list[PaperRecord]) -> None:
        for record in papers:
            self.papers[record.paper_id] = record
