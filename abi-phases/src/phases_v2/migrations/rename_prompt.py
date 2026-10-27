"""Fold the ``logical_sentences`` prompt into ``conditional_statement``.

Every id in the datasets is derived from content: a prompt's id from its name
and text, an extraction's from its chunk, model and prompt id, an item's from
its extraction id. Renaming a prompt therefore changes the id of everything
extracted under it, so the rows cannot be edited in place — they are re-derived
under the new prompt id with :mod:`phases_v2.identity`, and the old ones are
removed.

What stays exactly as it was: the template (it is what the model received, so
the new prompt carries the stored text, not a rewrite of it), every
extraction's ``response`` and ``raw_response``, and its model, run and
timestamps. What changes: the prompt's name, and every id derived from it.

The vector collection is a projection, so it is not re-keyed. The old points and
their ledger entries are deleted, and the next vector projection embeds the
items again under their new ids.

Safe to run more than once. Re-keying is an upsert, deleting what is already
gone does nothing, and the old rows are the work list, so a run that stopped
half way resumes from what is left. Nothing is deleted until every re-keyed row
has been read back. A rerun after a complete run finds no old prompt and does
nothing.

Run on the deployment with::

    uv run abi run script src/phases_v2/migrations/rename_prompt.py [--dry-run]
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Protocol

from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2 import identity
from phases_v2.datasets import store
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.schemas import NAMESPACE
from phases_v2.extraction.interfaces import SUCCEEDED
from phases_v2.projection.interfaces import GRAPH
from phases_v2.prompts.domain import PromptTemplate, register_prompts
from phases_v2.sql import in_list, literal

OLD_NAME = "logical_sentences"
NEW_NAME = "conditional_statement"
ITEMS_COLLECTION = "phases_v2_extracted_items"

_BATCH = 500


class MigrationError(RuntimeError):
    """Something is not as the migration expects; nothing was deleted."""


class VectorPoints(Protocol):
    """The vector points that carry the old prompt's name or ids."""

    def count(self, prompt_ids: list[str], prompt_name: str) -> int: ...

    def delete(self, prompt_ids: list[str], prompt_name: str) -> None: ...


class QdrantVectorPoints:
    """Points are matched on their payload rather than on derived point ids, so
    a point whose dataset row has already gone is removed too."""

    def __init__(self, client: Any, collection: str = ITEMS_COLLECTION):
        self._client = client
        self._collection = collection

    def _filter(self, prompt_ids: list[str], prompt_name: str):
        from qdrant_client import models as qm

        should = [
            qm.FieldCondition(key="prompt_name", match=qm.MatchValue(value=prompt_name))
        ]
        if prompt_ids:
            should.append(
                qm.FieldCondition(key="prompt_id", match=qm.MatchAny(any=prompt_ids))
            )
        return qm.Filter(should=should)

    def count(self, prompt_ids: list[str], prompt_name: str) -> int:
        if not self._client.collection_exists(self._collection):
            return 0
        return self._client.count(
            self._collection,
            count_filter=self._filter(prompt_ids, prompt_name),
            exact=True,
        ).count

    def delete(self, prompt_ids: list[str], prompt_name: str) -> None:
        from qdrant_client import models as qm

        if not self._client.collection_exists(self._collection):
            return
        self._client.delete(
            self._collection,
            points_selector=qm.FilterSelector(
                filter=self._filter(prompt_ids, prompt_name)
            ),
            wait=True,
        )


@dataclass
class Report:
    dry_run: bool
    before: dict[str, int] = field(default_factory=dict)
    after: dict[str, int] = field(default_factory=dict)

    def render(self) -> str:
        width = max(map(len, self.before), default=0)
        title = f"rename {OLD_NAME} -> {NEW_NAME}"
        if self.dry_run:
            title += " (dry run: nothing changed; 'after' is what a real run leaves)"
        lines = [title, f"{'':{width}}  {'before':>8}  {'after':>8}"]
        for label, before in self.before.items():
            lines.append(f"{label:{width}}  {before:>8}  {self.after[label]:>8}")
        return "\n".join(lines)


# -- reading --------------------------------------------------------------


def _query(dataset: DatasetService, sql: str) -> list[dict[str, Any]]:
    return dataset.query(sql, namespace=NAMESPACE).rows


def _batches(values: list[str]):
    unique = sorted(set(values))
    for start in range(0, len(unique), _BATCH):
        yield unique[start : start + _BATCH]


def _select(
    dataset: DatasetService, table: str, column: str, values: list[str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for batch in _batches(values):
        rows.extend(
            _query(
                dataset,
                f"SELECT * FROM {table} WHERE {column} IN {in_list(batch)}",  # nosec B608 - table and column are literals in this module
            )
        )
    return rows


def _count(
    dataset: DatasetService,
    table: str,
    column: str,
    values: list[str],
    *,
    where: str = "TRUE",
) -> int:
    return sum(
        int(
            _query(
                dataset,
                f"SELECT count(*) AS n FROM {table} "  # nosec B608
                f"WHERE {column} IN {in_list(batch)} AND {where}",
            )[0]["n"]
        )
        for batch in _batches(values)
    )


def _mentions(value: Any, ids: set[str]) -> bool:
    text = json.dumps(value)
    return any(identifier in text for identifier in ids)


def _replace_ids(value: Any, mapping: dict[str, str]) -> Any:
    """``value`` with every id in ``mapping`` swapped, wherever it is nested.

    Order is kept, and an id is never listed twice: a request that named both
    the old and the new prompt would otherwise run it twice.
    """
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        swapped: list[Any] = []
        for item in (_replace_ids(item, mapping) for item in value):
            if item not in swapped:
                swapped.append(item)
        return swapped
    if isinstance(value, dict):
        return {key: _replace_ids(item, mapping) for key, item in value.items()}
    return value


@dataclass
class _Plan:
    """What the old rows say should exist under the new ids."""

    prompts: dict[str, PromptTemplate]  # old prompt id -> the prompt it becomes
    extractions: list[dict[str, Any]]
    items: list[dict[str, Any]]
    extraction_map: dict[str, str]  # old extraction id -> new
    item_map: dict[str, str]  # old item id -> new

    @property
    def old_prompt_ids(self) -> list[str]:
        return list(self.prompts)

    @property
    def new_prompt_ids(self) -> list[str]:
        return [prompt.prompt_id for prompt in self.prompts.values()]

    @property
    def prompt_map(self) -> dict[str, str]:
        return {old: new.prompt_id for old, new in self.prompts.items()}


def _plan(dataset: DatasetService) -> _Plan:
    old_prompts = _query(
        dataset,
        "SELECT prompt_id, template, output_key FROM prompts "
        f"WHERE name = {literal(OLD_NAME)} ORDER BY prompt_id",  # nosec B608
    )
    prompts = {
        row["prompt_id"]: PromptTemplate(
            name=NEW_NAME,
            template=row["template"],
            # The answer key is named after the prompt. The stored responses
            # keep the old key, which parsing still accepts.
            output_key=NEW_NAME if row["output_key"] == OLD_NAME else row["output_key"],
        )
        for row in old_prompts
    }
    extractions = _select(dataset, "extractions", "prompt_id", list(prompts))
    items = _select(dataset, "extracted_items", "prompt_id", list(prompts))

    extraction_map = {
        row["extraction_id"]: identity.extraction_id(
            row["chunk_id"], row["model_id"], prompts[row["prompt_id"]].prompt_id
        )
        for row in extractions
    }
    for item in items:
        if item["extraction_id"] not in extraction_map:
            # Without its extraction row an item has no model, so its new id
            # cannot be derived. Stopping is better than dropping it.
            raise MigrationError(
                f"item {item['item_id']} belongs to extraction "
                f"{item['extraction_id']}, which has no row"
            )
    item_map = {
        item["item_id"]: identity.item_id(
            extraction_map[item["extraction_id"]], item["seq"]
        )
        for item in items
    }
    return _Plan(prompts, extractions, items, extraction_map, item_map)


def _references(dataset: DatasetService, table: str, column: str, ids: set[str]):
    """Rows of a small table whose JSON ``column`` names any of ``ids``."""
    if not ids:
        return []
    return [
        row
        for row in _query(dataset, f"SELECT * FROM {table}")  # nosec B608 - literal table
        if _mentions(row[column], ids)
    ]


def _survey(
    dataset: DatasetService, points: VectorPoints, plan: _Plan
) -> dict[str, int]:
    old, new = plan.old_prompt_ids, plan.new_prompt_ids
    old_keys = list(plan.item_map) + list(plan.extraction_map)
    old_set = set(old)
    return {
        f"prompts named {OLD_NAME}": _count(dataset, "prompts", "prompt_id", old),
        f"prompts named {NEW_NAME} (from {OLD_NAME})": _count(
            dataset, "prompts", "prompt_id", new
        ),
        "extractions, old prompt id": _count(dataset, "extractions", "prompt_id", old),
        "extractions, new prompt id": _count(dataset, "extractions", "prompt_id", new),
        "extracted_items, old prompt id": _count(
            dataset, "extracted_items", "prompt_id", old
        ),
        "extracted_items, new prompt id": _count(
            dataset, "extracted_items", "prompt_id", new
        ),
        "extraction_runs, old prompt id": _count(
            dataset, "extraction_runs", "prompt_id", old
        ),
        "extraction_runs, new prompt id": _count(
            dataset, "extraction_runs", "prompt_id", new
        ),
        "probabilistic_relations, old prompt id": _count(
            dataset, "probabilistic_relations", "prompt_id", old
        ),
        "projections ledger, old item/extraction ids": _count(
            dataset, "projections", "key", old_keys
        ),
        "pipelines naming the old prompt": len(
            _references(dataset, "pipelines", "inputs", old_set)
        ),
        "run_requests naming the old prompt": len(
            _references(dataset, "run_requests", "prompt_ids", old_set)
        ),
        "qdrant points, old prompt": points.count(old, OLD_NAME),
    }


# -- writing --------------------------------------------------------------


def _write(rows: DatasetRowStore, table: str, new_rows: list[dict[str, Any]]) -> None:
    for start in range(0, len(new_rows), _BATCH):
        rows.write_rows(table, new_rows[start : start + _BATCH])


def _rekey(dataset: DatasetService, plan: _Plan) -> None:
    rows = DatasetRowStore(dataset)
    register_prompts(rows, list(plan.prompts.values()))
    prompt_map = plan.prompt_map

    # A succeeded extraction already at the new id is kept rather than
    # overwritten by an older copy of itself.
    already = {
        row["extraction_id"]
        for row in _select(
            dataset, "extractions", "extraction_id", list(plan.extraction_map.values())
        )
        if row["status"] == SUCCEEDED
    }
    rekeyed = {
        old: new for old, new in plan.extraction_map.items() if new not in already
    }

    _write(
        rows,
        "extractions",
        [
            row
            | {
                "extraction_id": plan.extraction_map[row["extraction_id"]],
                "prompt_id": prompt_map[row["prompt_id"]],
            }
            for row in plan.extractions
            if row["extraction_id"] in rekeyed
        ],
    )
    _write(
        rows,
        "extracted_items",
        [
            item
            | {
                "item_id": plan.item_map[item["item_id"]],
                "extraction_id": plan.extraction_map[item["extraction_id"]],
                "prompt_id": prompt_map[item["prompt_id"]],
            }
            for item in plan.items
            if item["extraction_id"] in rekeyed
        ],
    )
    # Same run, same key: this upsert replaces the row with the renamed one.
    _write(
        rows,
        "extraction_runs",
        [
            row | {"prompt_id": prompt_map[row["prompt_id"]]}
            for row in _select(
                dataset, "extraction_runs", "prompt_id", plan.old_prompt_ids
            )
        ],
    )
    old_set = set(plan.old_prompt_ids)
    _write(
        rows,
        "pipelines",
        [
            row | {"inputs": _replace_ids(row["inputs"], prompt_map)}
            for row in _references(dataset, "pipelines", "inputs", old_set)
        ],
    )
    _write(
        rows,
        "run_requests",
        [
            row | {"prompt_ids": _replace_ids(row["prompt_ids"], prompt_map)}
            for row in _references(dataset, "run_requests", "prompt_ids", old_set)
        ],
    )


def _verify(dataset: DatasetService, plan: _Plan) -> None:
    """Read every re-keyed row back, so nothing is deleted on a hope."""
    for table, column, expected in (
        ("extractions", "extraction_id", set(plan.extraction_map.values())),
        ("extracted_items", "item_id", set(plan.item_map.values())),
    ):
        found = {row[column] for row in _select(dataset, table, column, list(expected))}
        if found != expected:
            raise MigrationError(
                f"{len(expected - found)} re-keyed {table} rows are missing; "
                "the old rows were left in place"
            )


def _drop_old(dataset: DatasetService, points: VectorPoints, plan: _Plan) -> None:
    """Delete the old projections first, then the rows they were made from.

    The old rows are the work list, so they go last: a run that stops before
    then still knows which ledger entries and points to remove when repeated.
    """
    old_keys = list(plan.item_map) + list(plan.extraction_map)
    store.delete_rows(dataset, "projections", "key", old_keys)
    if points.count(plan.old_prompt_ids, OLD_NAME):
        points.delete(plan.old_prompt_ids, OLD_NAME)

    store.delete_rows(dataset, "extracted_items", "prompt_id", plan.old_prompt_ids)
    store.delete_rows(dataset, "extractions", "prompt_id", plan.old_prompt_ids)
    store.delete_rows(dataset, "prompts", "prompt_id", plan.old_prompt_ids)


def _expected_after(
    dataset: DatasetService, before: dict[str, int], plan: _Plan
) -> dict[str, int]:
    """What a real run would leave, worked out without writing anything."""
    after = dict.fromkeys(before, 0)
    new_extractions = set(plan.extraction_map.values())
    new_items = set(plan.item_map.values())
    existing_extractions = {
        row["extraction_id"]
        for row in _select(
            dataset, "extractions", "extraction_id", list(new_extractions)
        )
    }
    existing_items = {
        row["item_id"]
        for row in _select(dataset, "extracted_items", "item_id", list(new_items))
    }
    after[f"prompts named {NEW_NAME} (from {OLD_NAME})"] = len(plan.prompts)
    after["extractions, new prompt id"] = len(existing_extractions | new_extractions)
    after["extracted_items, new prompt id"] = len(existing_items | new_items)
    after["extraction_runs, new prompt id"] = (
        before["extraction_runs, new prompt id"]
        + before["extraction_runs, old prompt id"]
    )
    after["probabilistic_relations, old prompt id"] = before[
        "probabilistic_relations, old prompt id"
    ]
    return after


def migrate(
    dataset: DatasetService, points: VectorPoints, *, dry_run: bool = False
) -> Report:
    plan = _plan(dataset)
    report = Report(dry_run=dry_run)
    report.before = _survey(dataset, points, plan)

    if report.before["probabilistic_relations, old prompt id"]:
        raise MigrationError(
            f"{OLD_NAME} has relation rows, which this migration does not re-key"
        )
    in_graph = _count(
        dataset,
        "projections",
        "key",
        list(plan.extraction_map),
        where=f"target = {literal(GRAPH)}",
    )
    if in_graph:
        raise MigrationError(
            f"{in_graph} {OLD_NAME} extractions are in the graph, which this "
            "migration does not rewrite"
        )

    if dry_run:
        report.after = _expected_after(dataset, report.before, plan)
        return report

    if plan.prompts:
        _rekey(dataset, plan)
        _verify(dataset, plan)
    # Also when no old prompt is left: points written by an earlier projection
    # can outlive the rows they were made from.
    _drop_old(dataset, points, plan)
    report.after = _survey(dataset, points, plan)
    return report


def main(engine: Any, argv: list[str]) -> Report:
    from naas_abi_core.services.vector_store.adapters.QdrantAdapter import (
        QdrantAdapter,
    )

    adapter = engine.services.vector_store.adapter
    if not isinstance(adapter, QdrantAdapter):
        raise MigrationError("the vector store is not Qdrant; nothing was changed")
    report = migrate(
        engine.services.dataset,
        QdrantVectorPoints(adapter.client),
        dry_run="--dry-run" in argv,
    )
    print(report.render(), flush=True)
    return report


if __name__ == "__main__":
    from phases_v2 import ABIModule

    main(ABIModule.get_instance().engine, sys.argv[1:])
