"""The ``papers`` and ``paper_paths`` datasets, as the domain's :class:`PaperStore`."""

from __future__ import annotations

from datetime import datetime

from phases_v2.papers.interfaces import PaperRecord
from phases_v2.ports import RowStore


class DatasetPaperStore:
    def __init__(self, rows: RowStore):
        self._rows = rows

    def already_ingested(self) -> dict[str, str | None]:
        return {
            row["paper_id"]: row["text_key"]
            for row in self._rows.query("SELECT paper_id, text_key FROM papers")
        }

    def save(self, papers: list[PaperRecord]) -> None:
        self._rows.write_rows(
            "papers",
            [
                {
                    "paper_id": record.paper_id,
                    "storage_prefix": record.storage_prefix,
                    "storage_key": record.storage_key,
                    "file_name": record.file_name,
                    "content_sha256": record.content_sha256,
                    "size_bytes": record.size_bytes,
                    "mime_type": record.mime_type,
                    "text_key": record.text_key,
                    "discovered_at": record.discovered_at,
                }
                for record in papers
            ],
        )

    def save_paths(self, paths: dict[str, str], seen_at: datetime) -> None:
        self._rows.write_rows(
            "paper_paths",
            [
                {"path": path, "paper_id": paper_id, "seen_at": seen_at}
                for path, paper_id in paths.items()
            ],
        )
