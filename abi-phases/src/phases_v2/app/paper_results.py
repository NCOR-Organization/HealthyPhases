"""Everything extracted from one paper, grouped by prompt version and model.

The page a user opens from Results, Search, Collections, Runs or the Library:
the paper's PubMed and OpenAlex records when it has them, what ran on it, and
each prompt version × model's items with the chunk each came from, its failed
chunks with their errors, and its probability relations.

Read-only. Every read is scoped to the one paper, so the cost follows the
paper's own results rather than the corpus.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any

from phases_v2.app.app_resources import ResourceNotFound
from phases_v2.app.paper_links import PaperFacts, requests_including
from phases_v2.app.papers_catalog import paper_path
from phases_v2.ports import RowStore
from phases_v2.search.models import ItemLocation, SearchHit
from phases_v2.search.paths import source_folder
from phases_v2.sources.library_links import (
    linked_schemas,
    openalex_record,
    pubmed_pmid,
    pubmed_record,
)
from phases_v2.sql import in_list, literal
from phases_v2.structured_text import canonical_payload_text

#: A failed extraction keeps the start of what the model returned, enough to see why.
RAW_EXCERPT_CHARS = 600

RELATION_FIELDS = (
    "subject_process",
    "subject_participant",
    "target_process",
    "direction",
    "evidence_text",
)


class PaperResults:
    def __init__(self, rows: RowStore | None):
        self._rows = rows

    def paper(self, paper_id: str) -> dict[str, Any]:
        rows = self._require_rows()
        schemas = linked_schemas(rows)
        paper = self._paper_row(paper_id, schemas)
        groups, chunks, run_ids = self._results(paper_id)
        paths = [
            row["path"]
            for row in rows.query(
                "SELECT path FROM paper_paths "  # nosec B608
                f"WHERE paper_id = {literal(paper_id)} ORDER BY path"
            )
        ]
        pubmed = pubmed_record(rows, schemas, paper["pmid"])
        if pubmed and (pubmed.get("title") or "").strip():
            paper["title"] = pubmed["title"]
        return {
            "paper": dict(paper, paths=paths),
            "pubmed": pubmed,
            "openalex": openalex_record(rows, schemas, paper["pmid"]),
            "chunkers": [
                {"chunker_id": row["chunker_id"], "chunks": int(row["chunks"])}
                for row in rows.query(
                    "SELECT chunker_id, count(*) AS chunks FROM chunks "  # nosec B608
                    f"WHERE paper_id = {literal(paper_id)} "
                    "GROUP BY chunker_id ORDER BY chunker_id"
                )
            ],
            "ran": [_summary(group) for group in groups],
            "requests": requests_including(
                rows,
                PaperFacts.of(paper, paths, run_ids),
            ),
            "results": groups,
            "chunks": chunks,
        }

    def hits(
        self, paper_id: str, prompt_id: str = "", model_id: str | None = None
    ) -> Iterator[SearchHit]:
        """The paper's results as search export rows: one per item, or one per
        relation for items that carry relations.

        ``prompt_id`` keeps one version. ``model_id`` keeps one model; an empty
        one keeps the results whose model is unknown, and None keeps every model.
        Reads only the results, not the paper's records or runs.
        """
        paper = self._paper_row(paper_id, set())
        groups, chunks, _ = self._results(paper_id)
        for group in groups:
            if (prompt_id and group["prompt_id"] != prompt_id) or (
                model_id is not None and (group["model_id"] or "") != model_id
            ):
                continue
            for item in group["items"]:
                chunk = chunks.get(item["chunk_id"]) or {}
                hit = SearchHit.build(
                    item_id=item["item_id"],
                    extracted_text=item["text"],
                    location=ItemLocation(
                        prompt_id=group["prompt_id"],
                        prompt_name=group["prompt_name"],
                        prompt_template=group["template"],
                        model_id=group["model_id"],
                        chunk_id=item["chunk_id"],
                        chunk_seq=chunk.get("seq"),
                        chunk_text=chunk.get("text"),
                        paper_id=paper["paper_id"],
                        paper_name=paper["file_name"],
                        source_path=source_folder(
                            paper["storage_prefix"], paper["storage_key"]
                        ),
                    ),
                )
                if not item["relations"]:
                    yield hit
                for relation in item["relations"]:
                    yield replace(hit, **relation)

    def _results(
        self, paper_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
        """The paper's result groups, the chunks they refer to and their run ids."""
        rows = self._require_rows()
        extractions = rows.query(
            "SELECT e.extraction_id, e.prompt_id, e.model_id, e.status, e.error, "  # nosec B608
            f"substr(e.raw_response, 1, {RAW_EXCERPT_CHARS + 1}) AS raw_excerpt, "
            "e.item_count, e.run_id, e.completed_at, c.chunk_id, c.seq, c.chunker_id "
            "FROM extractions e JOIN chunks c ON c.chunk_id = e.chunk_id "
            f"WHERE c.paper_id = {literal(paper_id)} ORDER BY c.seq, e.extraction_id"
        )
        # An item's model is its extraction's, which the rows above already hold.
        model_of = {row["extraction_id"]: row["model_id"] for row in extractions}
        items = [
            dict(row, model_id=model_of.get(row["extraction_id"]))
            for row in rows.query(
                "SELECT item_id, extraction_id, chunk_id, seq, text, prompt_id "  # nosec B608
                f"FROM extracted_items WHERE paper_id = {literal(paper_id)} "
                "ORDER BY extraction_id, seq, item_id"
            )
        ]
        relations: dict[str, list[dict[str, Any]]] = {}
        for row in rows.query(
            f"SELECT relation_id, item_id, {', '.join(RELATION_FIELDS)} "  # nosec B608
            f"FROM probabilistic_relations WHERE paper_id = {literal(paper_id)} "
            "ORDER BY item_id, relation_index, relation_id"
        ):
            relations.setdefault(row["item_id"], []).append(
                {key: row[key] for key in ("relation_id", *RELATION_FIELDS)}
            )
        prompt_ids = sorted(
            {row["prompt_id"] for row in extractions}
            | {row["prompt_id"] for row in items}
        )
        prompts = {
            row["prompt_id"]: row
            for row in rows.query(
                "SELECT prompt_id, name, template, output_key, registered_at "  # nosec B608
                f"FROM prompts WHERE prompt_id IN {in_list(prompt_ids)}"
            )
        }
        chunk_ids = sorted(
            {row["chunk_id"] for row in extractions}
            | {row["chunk_id"] for row in items if row["chunk_id"]}
        )
        chunks = {
            row["chunk_id"]: {
                "chunk_id": row["chunk_id"],
                "seq": int(row["seq"]),
                "chunker_id": row["chunker_id"],
                "text": row["text"],
            }
            for row in rows.query(
                "SELECT chunk_id, seq, chunker_id, text FROM chunks "  # nosec B608
                f"WHERE paper_id = {literal(paper_id)} "
                f"AND chunk_id IN {in_list(chunk_ids)} ORDER BY chunker_id, seq"
            )
        }
        # Items in reading order: by chunk position, then as extracted.
        items.sort(
            key=lambda row: (
                chunks.get(row["chunk_id"], {}).get("seq", float("inf")),
                row["extraction_id"],
                row["seq"],
                row["item_id"],
            )
        )
        groups = _groups(extractions, items, relations, prompts, chunks)
        return groups, chunks, [row["run_id"] for row in extractions if row["run_id"]]

    def _paper_row(self, paper_id: str, schemas: set[str]) -> dict[str, Any]:
        """The ``papers`` row; its PMID is looked up only when ``schemas`` has PubMed."""
        rows = self._require_rows()
        found = rows.query(
            "SELECT paper_id, file_name, storage_prefix, storage_key, "  # nosec B608
            "content_sha256, size_bytes, discovered_at, "
            "text_key IS NOT NULL AS ingested FROM papers "
            f"WHERE paper_id = {literal(paper_id)} LIMIT 1"
        )
        if not found:
            raise ResourceNotFound("That paper is not in the corpus.")
        row = found[0]
        pmid = pubmed_pmid(rows, schemas, row["content_sha256"])
        return {
            "paper_id": row["paper_id"],
            "title": row["file_name"] or row["paper_id"],
            "file_name": row["file_name"],
            "storage_prefix": row["storage_prefix"],
            "storage_key": row["storage_key"],
            "path": paper_path(row["storage_prefix"], row["storage_key"]),
            "content_sha256": row["content_sha256"],
            "size_bytes": row["size_bytes"],
            "discovered_at": _iso(row["discovered_at"]),
            "ingested": bool(row["ingested"]),
            "source": "pubmed" if pmid else "file",
            "pmid": pmid,
        }

    def _require_rows(self) -> RowStore:
        if self._rows is None:
            raise ResourceNotFound("Paper results are unavailable in this deployment.")
        return self._rows


def _groups(extractions, items, relations, prompts, chunks) -> list[dict[str, Any]]:
    """One group per prompt version × model, in prompt-name order, newest version first."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}

    def group(prompt_id: str, model_id: str | None) -> dict[str, Any]:
        key = (prompt_id, model_id or "")
        if key not in groups:
            prompt = prompts.get(prompt_id) or {}
            groups[key] = {
                "prompt_id": prompt_id,
                "prompt_name": prompt.get("name") or prompt_id,
                "template": prompt.get("template"),
                "output_key": prompt.get("output_key"),
                "prompt_registered_at": _iso(prompt.get("registered_at")),
                "model_id": model_id,
                "chunker_ids": [],
                "succeeded": 0,
                "failed": 0,
                "item_count": 0,
                "relation_count": 0,
                "run_ids": [],
                "last_completed_at": None,
                "items": [],
                "failures": [],
            }
        return groups[key]

    for row in extractions:
        entry = group(row["prompt_id"], row["model_id"])
        if row["chunker_id"] not in entry["chunker_ids"]:
            entry["chunker_ids"].append(row["chunker_id"])
        if row["run_id"] and row["run_id"] not in entry["run_ids"]:
            entry["run_ids"].append(row["run_id"])
        completed = _iso(row["completed_at"])
        if completed and (
            entry["last_completed_at"] is None
            or str(completed) > str(entry["last_completed_at"])
        ):
            entry["last_completed_at"] = completed
        if row["status"] == "succeeded":
            entry["succeeded"] += 1
            continue
        entry["failed"] += 1
        raw = row["raw_excerpt"] or ""
        entry["failures"].append(
            {
                "extraction_id": row["extraction_id"],
                "chunk_id": row["chunk_id"],
                "seq": int(row["seq"]),
                "status": row["status"],
                "error": row["error"],
                "raw_excerpt": raw[:RAW_EXCERPT_CHARS]
                + ("…" if len(raw) > RAW_EXCERPT_CHARS else ""),
                "completed_at": completed,
            }
        )
    for row in items:
        entry = group(row["prompt_id"], row["model_id"])
        found = relations.get(row["item_id"], [])
        entry["item_count"] += 1
        entry["relation_count"] += len(found)
        chunk = chunks.get(row["chunk_id"]) or {}
        entry["items"].append(
            {
                "item_id": row["item_id"],
                "extraction_id": row["extraction_id"],
                "chunk_id": row["chunk_id"],
                "chunk_seq": chunk.get("seq"),
                "seq": row["seq"],
                "text": canonical_payload_text(row["text"] or ""),
                "relations": found,
            }
        )
    for entry in groups.values():
        entry["chunker_ids"].sort()
        entry["run_ids"].sort()
        entry["request_ids"] = sorted(
            {
                run_id[: -len(entry["prompt_id"]) - 1]
                for run_id in entry["run_ids"]
                if run_id.endswith(f":{entry['prompt_id']}")
            }
        )
    newest_first = sorted(
        groups.values(),
        key=lambda g: (str(g["prompt_registered_at"] or ""), g["prompt_id"]),
        reverse=True,
    )
    return sorted(
        newest_first,
        key=lambda g: (str(g["prompt_name"]).casefold(), g["model_id"] or ""),
    )


def _summary(group: dict[str, Any]) -> dict[str, Any]:
    return {
        key: group[key]
        for key in (
            "prompt_id",
            "prompt_name",
            "prompt_registered_at",
            "model_id",
            "chunker_ids",
            "succeeded",
            "failed",
            "item_count",
            "relation_count",
            "request_ids",
            "last_completed_at",
        )
    }


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value
