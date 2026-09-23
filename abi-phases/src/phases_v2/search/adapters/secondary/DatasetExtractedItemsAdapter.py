"""Extracted-items adapter backed by the module's datasets.

Datasets are the system of record for this module (see the README), so
provenance and keyword search are answered straight from the ``extracted_items``
dataset joined against ``extractions``, ``chunks``, ``papers`` and ``prompts`` —
not from the projected triple store, which is a rebuildable copy and can lag
behind what was actually extracted.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Any

from naas_abi_core import logger
from naas_abi_core.services.object_storage.ObjectStoragePort import Exceptions

from phases_v2.ports import RowStore
from phases_v2.search.models import ItemLocation, SearchHit
from phases_v2.search.paths import matches_path, parent_paths, source_folder
from phases_v2.search.search_keywords import exact_pattern, is_exact, tokenize
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
    def __init__(
        self, rows: RowStore, object_storage=None, papers_root: str = "phases_v2"
    ):
        self._rows = rows
        self._storage = object_storage
        self._papers_root = papers_root.strip("/")

    def _query(self, sql: str) -> list[dict[str, Any]]:
        try:
            return self._rows.query(sql)
        except Exception as exc:
            logger.error(f"Extracted-items query failed: {exc}")
            raise

    def download_paper(self, item_id: str) -> tuple[str, bytes]:
        if self._storage is None:
            raise FileNotFoundError("Source PDF is unavailable.")
        rows = self._query(
            "SELECT p.storage_prefix, p.storage_key, p.file_name "
            "FROM extracted_items ei JOIN papers p ON p.paper_id = ei.paper_id "
            f"WHERE ei.item_id = {literal(item_id)} LIMIT 1"
        )
        if not rows:
            raise FileNotFoundError("Source PDF is unavailable.")
        row = rows[0]
        prefix, key = row.get("storage_prefix") or "", row.get("storage_key") or ""
        root = self._papers_root
        # Never let a corrupted corpus row address another module or a local path.
        parts = (prefix + "/" + key).split("/")
        if (
            not root
            or not key
            or prefix.startswith("/")
            or key.startswith("/")
            or "\\" in prefix + key
            or "\x00" in prefix + key
            or any(part in {".", ".."} for part in parts)
            or not (prefix == root or prefix.startswith(root + "/"))
            or PurePosixPath(key).suffix.lower() != ".pdf"
        ):
            raise FileNotFoundError("Source PDF is unavailable.")
        try:
            content = self._storage.get_object(prefix, key)
        except Exceptions.ObjectNotFound as missing:
            raise FileNotFoundError("Source PDF is unavailable.") from missing
        if not content.startswith(b"%PDF-"):
            raise FileNotFoundError("Source PDF is unavailable.")
        return PurePosixPath(key).name, content

    def effects_page(
        self,
        target,
        direction,
        subject,
        participant,
        limit,
        offset,
        prompts=None,
        models=None,
        paths=None,
    ) -> tuple[list[SearchHit], int]:
        filters = []
        if direction:
            filters.append(f"r.direction = {literal(direction)}")
        for column, query in (
            ("target_process", target),
            ("subject_process", subject),
            ("subject_participant", participant),
        ):
            for token in tokenize(query):
                if is_exact(token):
                    pattern = exact_pattern(token, word_chars=r"\p{L}\p{N}_")
                    filters.append(
                        f"regexp_matches(LOWER(r.{column}), {literal(pattern)})"
                    )
                else:
                    filters.append(f"contains(LOWER(r.{column}), {literal(token)})")
        if prompts:
            filters.append(f"pr.name IN {in_list(prompts)}")
        if models:
            filters.append(f"e.model_id IN {in_list(models)}")
        if paths:
            filters.append(f"ei.paper_id IN {in_list(self.paper_ids_for_paths(paths))}")
        source = _FROM + " JOIN probabilistic_relations r ON r.item_id = ei.item_id "
        where = " WHERE " + " AND ".join(filters) if filters else ""
        total = int(
            self._query(f"SELECT COUNT(*) AS total {source} {where}")[0]["total"]
        )
        fields = (
            "subject_process",
            "subject_change",
            "subject_participant",
            "target_process",
            "direction",
            "evidence_text",
        )
        columns = ", ".join(f"r.{field}" for field in fields)
        rows = self._query(
            f"SELECT {_COLUMNS}, r.relation_id, {columns} {source} {where} "
            f"ORDER BY p.file_name, c.seq, r.relation_id LIMIT {int(limit)} OFFSET {int(offset)}"
        )
        hits = []
        for row in rows:
            relation = {field: row[field] for field in fields}
            hits.append(
                replace(
                    SearchHit.build(
                        item_id=row["item_id"],
                        extracted_text=json.dumps(relation, ensure_ascii=False),
                        location=_row_to_location(row),
                    ),
                    relation_id=row["relation_id"],
                    **relation,
                )
            )
        return hits, total

    def matching_item_ids(self, prompts=None, models=None, paths=None) -> set[str]:
        where = []
        if prompts:
            where.append(f"pr.name IN {in_list(prompts)}")
        if models:
            where.append(f"e.model_id IN {in_list(models)}")
        if paths:
            where.append(f"ei.paper_id IN {in_list(self.paper_ids_for_paths(paths))}")
        sql = "SELECT ei.item_id FROM extracted_items ei "
        if prompts:
            sql += "LEFT JOIN prompts pr ON pr.prompt_id = ei.prompt_id "
        if models:
            sql += "LEFT JOIN extractions e ON e.extraction_id = ei.extraction_id "
        if where:
            sql += "WHERE " + " AND ".join(where)
        return {row["item_id"] for row in self._query(sql)}

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

    def snapshot(self) -> int | None:
        return self._rows.snapshot()

    def at_snapshot(self, snapshot: int | None):
        return DatasetExtractedItemsAdapter(
            self._rows.at_snapshot(snapshot), self._storage, self._papers_root
        )

    def _keyword_where(self, tokens, prompts, models, paths) -> str:
        if not tokens:
            return "WHERE FALSE"
        clauses = []
        for token in tokens:
            if is_exact(token):
                pattern = exact_pattern(token, word_chars=r"\p{L}\p{N}_")
                clauses.append(f"regexp_matches(LOWER(ei.text), {literal(pattern)})")
            else:
                clauses.append(f"LOWER(ei.text) LIKE {literal(f'%{token}%')}")
        filters = " AND ".join(clauses)
        where = f"WHERE {filters}"
        if prompts:
            where += f" AND pr.name IN {in_list(prompts)}"
        if models:
            where += f" AND e.model_id IN {in_list(models)}"
        if paths:
            where += f" AND ei.paper_id IN {in_list(self.paper_ids_for_paths(paths))}"
        return where

    def keyword_count(self, tokens, prompts=None, models=None, paths=None) -> int:
        where = self._keyword_where(tokens, prompts, models, paths)
        source = "FROM extracted_items ei"
        if prompts:
            source += " LEFT JOIN prompts pr ON pr.prompt_id = ei.prompt_id"
        if models:
            source += " LEFT JOIN extractions e ON e.extraction_id = ei.extraction_id"
        return int(
            self._query(f"SELECT COUNT(*) AS total {source} {where}")[0]["total"]
        )

    def keyword_search(
        self,
        tokens: list[str],
        prompts: list[str] | None,
        limit: int,
        models: list[str] | None = None,
        paths: list[str] | None = None,
        offset: int = 0,
    ) -> list[tuple[str, str, ItemLocation]]:
        where = self._keyword_where(tokens, prompts, models, paths)
        sql = (
            f"SELECT {_COLUMNS} {_FROM} {where} "
            f"ORDER BY p.file_name, c.seq, ei.item_id LIMIT {int(limit)} OFFSET {int(offset)}"
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
