"""The ``papers`` dataset, as the domain's :class:`PaperStore`."""

from __future__ import annotations

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
