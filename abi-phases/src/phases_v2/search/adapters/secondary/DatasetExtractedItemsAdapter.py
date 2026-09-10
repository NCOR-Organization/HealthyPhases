"""Extracted-items adapter backed by the module's datasets.

Datasets are the system of record for this module (see the README), so
provenance and keyword search are answered straight from the ``extracted_items``
dataset joined against ``extractions``, ``chunks``, ``papers`` and ``prompts`` —
not from the projected triple store, which is a rebuildable copy and can lag
behind what was actually extracted.
"""

from __future__ import annotations

from typing import Any

from naas_abi_core import logger

from phases_v2.ports import RowStore
from phases_v2.search.models import ItemLocation
from phases_v2.search.paths import matches_path, parent_paths, source_folder
from phases_v2.sql import in_list, literal

# Shared FROM/JOIN so provenance columns line up the same way for both queries
# below. Every join is LEFT: a row whose paper/chunk/prompt is missing (should
# never happen, but datasets carry no foreign-key enforcement) still resolves,
# with those columns simply null instead of dropping the item entirely.
_FROM = """
FROM extracted_items ei
LEFT JOIN extractions e ON e.extraction_id = ei.extraction_id
LEFT JOIN chunks c ON c.chunk_id = ei.chunk_id
LEFT JOIN papers p ON p.paper_id = ei.paper_id
LEFT JOIN prompts pr ON pr.prompt_id = ei.prompt_id
"""

_COLUMNS = """
    ei.item_id AS item_id,
    ei.text AS text,
    ei.prompt_id AS prompt_id,
    pr.name AS prompt_name,
    pr.template AS prompt_template,
    e.model_id AS model_id,
    ei.chunk_id AS chunk_id,
    c.seq AS chunk_seq,
    c.text AS chunk_text,
    ei.paper_id AS paper_id,
    p.file_name AS paper_name,
    p.storage_prefix AS storage_prefix,
    p.storage_key AS storage_key
"""


def _row_to_location(row: dict[str, Any]) -> ItemLocation:
    return ItemLocation(
        prompt_id=row.get("prompt_id"),
        prompt_name=row.get("prompt_name"),
        model_id=row.get("model_id"),
        chunk_id=row.get("chunk_id"),
        chunk_seq=row.get("chunk_seq"),
        chunk_text=row.get("chunk_text"),
        paper_id=row.get("paper_id"),
        paper_name=row.get("paper_name"),
        source_path=source_folder(row.get("storage_prefix"), row.get("storage_key")),
        prompt_template=row.get("prompt_template"),
    )


class DatasetExtractedItemsAdapter:
    def __init__(self, rows: RowStore):
        self._rows = rows

    def _query(self, sql: str) -> list[dict[str, Any]]:
        try:
            return self._rows.query(sql)
        except Exception as exc:  # noqa: BLE001 - store down, bad SQL, etc.
            logger.error(f"Extracted-items query failed: {exc}")
            return []

    def resolve_locations(self, item_ids: list[str]) -> dict[str, ItemLocation]:
        unique_ids = list(dict.fromkeys(i for i in item_ids if i))
        if not unique_ids:
            return {}

        sql = (
            f"SELECT {_COLUMNS} {_FROM} "  # nosec B608 - values go through sql.literal
            f"WHERE ei.item_id IN {in_list(unique_ids)}"
        )
        return {
            row["item_id"]: _row_to_location(row)
            for row in self._query(sql)
            if row.get("item_id")
        }

    def keyword_search(
        self,
        tokens: list[str],
        prompts: list[str] | None,
        limit: int,
        models: list[str] | None = None,
        paths: list[str] | None = None,
    ) -> list[tuple[str, str, ItemLocation]]:
        if not tokens:
            return []

        filters = " AND ".join(
            f"LOWER(ei.text) LIKE {literal(f'%{token}%')}" for token in tokens
        )
        where = f"WHERE {filters}"
        if prompts:
            where = f"{where} AND pr.name IN {in_list(prompts)}"
        if models:
            where = f"{where} AND e.model_id IN {in_list(models)}"
        if paths:
            paper_ids = self.paper_ids_for_paths(paths)
            if not paper_ids:
                return []
            where = f"{where} AND ei.paper_id IN {in_list(paper_ids)}"

        sql = (
            f"SELECT {_COLUMNS} {_FROM} {where} "  # nosec B608 - values escaped via sql.literal
            f"ORDER BY p.file_name, c.seq LIMIT {int(limit)}"
        )
        return [
            (row["item_id"], row.get("text") or "", _row_to_location(row))
            for row in self._query(sql)
            if row.get("item_id")
        ]

    def list_prompts(self) -> list[str]:
        sql = (
            "SELECT DISTINCT pr.name AS prompt_name "
            "FROM extracted_items ei "
            "JOIN prompts pr ON pr.prompt_id = ei.prompt_id "
            "WHERE pr.name IS NOT NULL "
            "ORDER BY pr.name"
        )
        return [
            row["prompt_name"] for row in self._query(sql) if row.get("prompt_name")
        ]

    def list_models(self) -> list[str]:
        sql = (
            "SELECT DISTINCT e.model_id FROM extracted_items ei "
            "JOIN extractions e ON e.extraction_id = ei.extraction_id "
            "WHERE e.model_id IS NOT NULL AND e.model_id != '' ORDER BY e.model_id"
        )
        return [row["model_id"] for row in self._query(sql)]

    def _paper_paths(self) -> list[dict[str, Any]]:
        return self._query(
            "SELECT p.paper_id, p.storage_prefix, p.storage_key FROM papers p "
            "WHERE EXISTS (SELECT 1 FROM extracted_items ei WHERE ei.paper_id = p.paper_id)"
        )

    def list_paths(self) -> list[str]:
        return parent_paths(
            [
                folder
                for row in self._paper_paths()
                if (
                    folder := source_folder(
                        row.get("storage_prefix"), row.get("storage_key")
                    )
                )
            ]
        )

    def paper_ids_for_paths(self, paths: list[str]) -> list[str]:
        return sorted(
            {
                row["paper_id"]
                for row in self._paper_paths()
                if matches_path(
                    source_folder(row.get("storage_prefix"), row.get("storage_key")),
                    paths,
                )
            }
        )
