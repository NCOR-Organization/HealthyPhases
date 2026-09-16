"""Incremental, repeatable projection of saved probabilistic claims into rows."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from phases_v2.ports import RowStore
from phases_v2.sql import in_list, literal
from phases_v2.structured_text import canonical_payload_text

TARGET = "probabilistic_relations_v1"
RELATION_FIELDS = (
    "subject_process",
    "subject_participant",
    "target_process",
    "direction",
    "evidence_text",
)
SOURCE_FIELDS = (
    "item_id",
    "extraction_id",
    "chunk_id",
    "paper_id",
    "prompt_id",
    "model_id",
)


@dataclass
class BackfillReport:
    examined: int = 0
    projected: int = 0
    invalid: int = 0
    errors: dict[str, str] = field(default_factory=dict)


def project_relations(
    reader: RowStore,
    writer: RowStore,
    validate: Callable[[dict], None],
    *,
    batch_size: int = 500,
    dry_run: bool = False,
    paper_ids: list[str] | None = None,
) -> BackfillReport:
    """Read one pinned snapshot; commit rows before recording their item IDs."""
    if not 1 <= batch_size <= 5000:
        raise ValueError("batch_size must be between 1 and 5000")
    scope = (
        ""
        if paper_ids is None
        else (
            f"AND ei.paper_id IN {in_list(paper_ids)} " if paper_ids else "AND FALSE "
        )
    )
    report = BackfillReport()
    cursor = ""
    while True:
        batch = reader.query(
            "SELECT ei.item_id, ei.extraction_id, ei.chunk_id, ei.paper_id, "
            "ei.prompt_id, ei.text, e.model_id FROM extracted_items ei "
            "JOIN extractions e ON e.extraction_id = ei.extraction_id "
            "JOIN prompts p ON p.prompt_id = ei.prompt_id "
            "WHERE e.status = 'succeeded' AND p.output_key = 'relations' "
            f"{scope}AND ei.item_id > {literal(cursor)} "
            "AND NOT EXISTS (SELECT 1 FROM projections done "
            f"WHERE done.target = {literal(TARGET)} AND done.key = ei.item_id) "
            f"ORDER BY ei.item_id LIMIT {batch_size}"
        )
        if not batch:
            return report
        rows, completed = [], []
        for item in batch:
            report.examined += 1
            try:
                payload = json.loads(canonical_payload_text(item["text"]))
                relations = (
                    payload
                    if isinstance(payload, list)
                    else (
                        payload["relations"]
                        if isinstance(payload, dict) and "relations" in payload
                        else [payload]
                    )
                )
                if not isinstance(relations, list) or not 1 <= len(relations) <= 8:
                    raise ValueError("Expected one to eight relations")
                item_rows = []
                for index, relation in enumerate(relations):
                    if not isinstance(relation, dict):
                        raise ValueError("Relation is not an object")
                    row = {key: item[key] for key in SOURCE_FIELDS}
                    row.update({key: relation.get(key) for key in RELATION_FIELDS})
                    row.update(
                        relation_id=hashlib.sha256(
                            f"{item['item_id']}:{index}".encode()
                        ).hexdigest(),
                        relation_index=index,
                    )
                    validate(row)
                    item_rows.append(row)
            except (ValueError, TypeError, KeyError, RecursionError) as error:
                report.invalid += 1
                if len(report.errors) < 20:
                    report.errors[item["item_id"]] = str(error)
                continue
            rows.extend(item_rows)
            completed.append(item["item_id"])
        if rows and not dry_run:
            writer.write_rows("probabilistic_relations", rows)
            writer.write_rows(
                "projections",
                [
                    {
                        "target": TARGET,
                        "key": item_id,
                        "projected_at": datetime.now(UTC),
                    }
                    for item_id in completed
                ],
            )
        report.projected += len(rows)
        cursor = batch[-1]["item_id"]
