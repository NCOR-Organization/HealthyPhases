"""Read every stored failed answer again, under what we now accept.

A failed extraction whose model did answer keeps that answer verbatim in
``raw_response``. Many were rejected only for being a little over a length or
count limit that is now accepted (see "Accepted answers" in the README), so they
can be recovered without calling the model again.

For every ``failed`` extraction with a stored answer, any model and any prompt,
the answer is read through the same code as a live call
(:meth:`LangchainExtractionModel.reread`, then
:func:`phases_v2.extraction.domain.parse_items`):

- an answer that now passes is written exactly as a live success would be: its
  items first, with the ids a run derives (extraction + position), then the
  extraction row as ``succeeded`` with ``response`` and ``item_count`` set and
  ``error`` cleared. ``run_id`` and ``completed_at`` are kept: the answer came
  from that call;
- an answer still invalid stays ``failed``; its ``error`` is rewritten with the
  detailed reason only if that differs from the stored one;
- a failed call with no stored answer is not touched.

Nothing is projected here; the next projection run picks up the new items. Every
write goes through :mod:`phases_v2.datasets.store`. A second run finds nothing
to do: what passed is no longer failed, and what is still invalid already
carries its detailed reason.

Run on the deployment with::

    uv run abi run script src/phases_v2/migrations/recheck_failed_extractions.py -- --dry-run
    uv run abi run script src/phases_v2/migrations/recheck_failed_extractions.py
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.extraction.adapters.secondary.DatasetExtractionStore import (
    DatasetExtractionStore,
)
from phases_v2.extraction.adapters.secondary.LangchainExtractionModel import (
    LangchainExtractionModel,
    NotAToolCallMessage,
)
from phases_v2.extraction.domain import (
    Attempt,
    UnusableResponse,
    parse_items,
    rows_for,
)
from phases_v2.extraction.interfaces import (
    FAILED,
    LEGACY_OUTPUT_KEYS,
    SUCCEEDED,
    ChunkRef,
    ExtractedItemRecord,
    ExtractionRecord,
    InvalidAnswer,
)
from phases_v2.prompts.domain import PromptTemplate

# Reads a stored answer as a live call reads one: ``(raw_response, output_key)``
# to the validated answer text, or raises InvalidAnswer.
Reader = Callable[[str, str], str]

_BATCH = 500
# The answer key a renamed prompt used to have -> the key it has now.
_CURRENT_KEY = {
    legacy: current
    for current, legacies in LEGACY_OUTPUT_KEYS.items()
    for legacy in legacies
}

ACCEPTED = "now accepted"
REWRITTEN = "still invalid, reason rewritten"
UNCHANGED = "still invalid, reason unchanged"
NOT_A_MESSAGE = "left as is: stored answer is not a tool-call message"
NO_PROMPT = "left as is: prompt is not registered"
NO_CHUNK = "left as is: chunk no longer exists"
ID_MISMATCH = "left as is: extraction id does not match its chunk, model and prompt"


def reason(error: str | None) -> str:
    """``error`` reduced to its first problem, without positions or sizes.

    Groups the report: ``relations[3].evidence_text: length 630 exceeds 500``
    and ``relations[0].evidence_text: length 510 exceeds 500`` are one reason.
    """
    if not error:
        return "(no error)"
    text = re.sub(r" \(gave up after \d+ attempts\)$", "", error)
    head, _, rest = text.partition(": ")
    first = rest.split("; ")[0] if rest else ""
    text = f"{head}: {first}" if first else head
    text = re.sub(r"\[\d+\]", "[]", text)
    text = re.sub(r"length \d+", "length N", text)
    return re.sub(r": \d+ items", ": N items", text)


@dataclass(frozen=True)
class _Failed:
    record: ExtractionRecord
    paper_id: str | None
    prompt: PromptTemplate | None


@dataclass
class _Plan:
    """What each stored failed answer becomes."""

    outcomes: dict[str, str] = field(default_factory=dict)  # extraction id -> kind
    before: Counter = field(default_factory=Counter)
    after: Counter = field(default_factory=Counter)
    items: list[ExtractedItemRecord] = field(default_factory=list)
    extractions: list[ExtractionRecord] = field(default_factory=list)
    without_answer: int = 0


@dataclass
class Report:
    dry_run: bool
    before: Counter
    after: Counter
    outcomes: Counter
    items: int
    without_answer: int

    @property
    def changed(self) -> int:
        return self.outcomes[ACCEPTED] + self.outcomes[REWRITTEN]

    def render(self) -> str:
        title = "re-check of stored failed answers"
        if self.dry_run:
            title += " (dry run: nothing changed; 'after' is what a real run leaves)"
        keys = sorted(set(self.before) | set(self.after))
        header = ("prompt", "model", "reason")
        widths = [
            max([len(h)] + [len(key[n]) for key in keys]) for n, h in enumerate(header)
        ]
        line = "  ".join(f"{{:{w}}}" for w in widths) + "  {:>6}  {:>6}"
        lines = [title, line.format(*header, "before", "after")]
        for key in keys:
            lines.append(line.format(*key, self.before[key], self.after[key]))
        lines.append("")
        for kind in (
            ACCEPTED,
            REWRITTEN,
            UNCHANGED,
            NOT_A_MESSAGE,
            NO_PROMPT,
            NO_CHUNK,
            ID_MISMATCH,
        ):
            if self.outcomes[kind] or kind in (ACCEPTED, REWRITTEN, UNCHANGED):
                lines.append(f"{kind}: {self.outcomes[kind]}")
        lines.append(f"items written: {self.items}")
        lines.append(
            f"failed calls without a stored answer (not touched): {self.without_answer}"
        )
        if not self.changed:
            lines.append("nothing to do")
        return "\n".join(lines)


def _failed_answers(rows: DatasetRowStore) -> list[_Failed]:
    found = rows.query(
        f"""
        SELECT e.extraction_id, e.chunk_id, e.model_id, e.prompt_id, e.run_id,
               e.status, e.response, e.raw_response, e.error, e.item_count,
               e.completed_at, p.name AS prompt_name, p.template, p.output_key,
               c.paper_id
        FROM extractions e
        LEFT JOIN prompts p ON p.prompt_id = e.prompt_id
        LEFT JOIN chunks c ON c.chunk_id = e.chunk_id
        WHERE e.status = '{FAILED}' AND e.raw_response IS NOT NULL
        ORDER BY e.extraction_id
        """  # nosec B608 - FAILED is a module constant
    )
    return [
        _Failed(
            record=ExtractionRecord(
                extraction_id=row["extraction_id"],
                chunk_id=row["chunk_id"],
                model_id=row["model_id"],
                prompt_id=row["prompt_id"],
                run_id=row["run_id"],
                status=row["status"],
                response=row["response"],
                raw_response=row["raw_response"],
                error=row["error"],
                item_count=row["item_count"],
                completed_at=row["completed_at"],
            ),
            paper_id=row["paper_id"],
            prompt=(
                PromptTemplate(
                    name=row["prompt_name"],
                    template=row["template"],
                    output_key=row["output_key"],
                )
                if row["prompt_name"] is not None
                else None
            ),
        )
        for row in found
    ]


def _without_answer(rows: DatasetRowStore) -> int:
    return int(
        rows.query(
            "SELECT count(*) AS n FROM extractions "
            f"WHERE status = '{FAILED}' AND raw_response IS NULL"  # nosec B608
        )[0]["n"]
    )


def _recheck(failed: _Failed, read: Reader) -> tuple[str, Any]:
    """``(kind, detail)``: the rows to write for an accepted answer, the new
    error for one still invalid, or nothing for one left as it is."""
    record, prompt = failed.record, failed.prompt
    if prompt is None:
        return NO_PROMPT, None
    output_key = _CURRENT_KEY.get(prompt.output_key, prompt.output_key)
    try:
        text = read(record.raw_response or "", output_key)
        response, items = parse_items(text, output_key)
    except NotAToolCallMessage:
        return NOT_A_MESSAGE, None
    except (InvalidAnswer, UnusableResponse) as failure:
        error = str(failure)
        return (UNCHANGED, None) if error == record.error else (REWRITTEN, error)

    if failed.paper_id is None:
        return NO_CHUNK, None
    extraction, item_rows = rows_for(
        ChunkRef(chunk_id=record.chunk_id, paper_id=failed.paper_id, text=""),
        model_id=record.model_id,
        prompt=prompt,
        run_id=record.run_id,
        outcome=Attempt(SUCCEEDED, response, text, None, items),
        completed_at=record.completed_at,
    )
    if (
        prompt.prompt_id != record.prompt_id
        or extraction.extraction_id != record.extraction_id
    ):
        return ID_MISMATCH, None
    return ACCEPTED, (extraction, item_rows)


def _plan(rows: DatasetRowStore, read: Reader) -> _Plan:
    plan = _Plan(without_answer=_without_answer(rows))
    for failed in _failed_answers(rows):
        record = failed.record
        kind, detail = _recheck(failed, read)
        plan.outcomes[record.extraction_id] = kind
        plan.before[(record.prompt_id, record.model_id, reason(record.error))] += 1
        if kind == ACCEPTED:
            extraction, item_rows = detail
            plan.items.extend(item_rows)
            plan.extractions.append(extraction)
            after = SUCCEEDED
        elif kind == REWRITTEN:
            plan.extractions.append(replace(record, error=detail))
            after = reason(detail)
        else:
            after = reason(record.error)
        plan.after[(record.prompt_id, record.model_id, after)] += 1
    return plan


def _write(store: DatasetExtractionStore, plan: _Plan) -> None:
    """Every item first, then the extraction rows that own them.

    The extraction row is what marks a chunk done, so a run that stops half
    way leaves the rest still failed, and a repeat picks them up.
    """
    for start in range(0, len(plan.items), _BATCH):
        store.save_items(plan.items[start : start + _BATCH])
    for start in range(0, len(plan.extractions), _BATCH):
        store.save_extractions(plan.extractions[start : start + _BATCH])


def recheck(
    dataset: DatasetService,
    *,
    dry_run: bool = False,
    read: Reader = LangchainExtractionModel.reread,
) -> Report:
    rows = DatasetRowStore(dataset)
    plan = _plan(rows, read)
    if not dry_run:
        _write(DatasetExtractionStore(rows), plan)
    return Report(
        dry_run=dry_run,
        before=plan.before,
        after=plan.after,
        outcomes=Counter(plan.outcomes.values()),
        items=len(plan.items),
        without_answer=plan.without_answer,
    )


def main(engine: Any, argv: list[str]) -> Report:
    report = recheck(engine.services.dataset, dry_run="--dry-run" in argv)
    print(report.render(), flush=True)
    return report


if __name__ == "__main__":
    from phases_v2 import ABIModule

    main(ABIModule.get_instance().engine, sys.argv[1:])
