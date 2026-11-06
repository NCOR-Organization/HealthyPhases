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
- a failed call with no stored answer is not touched, nor is a stored answer
  that is not a tool-call message, or one whose prompt has no output contract;
- a failed call that kept an earlier invalid answer (its error starts with
  :data:`~phases_v2.extraction.interfaces.PROVIDER_FAILURE`) is accepted if
  that answer now passes, and otherwise left as it is: its error keeps saying
  the call failed, so the chunk is still counted as a failed call to run again.

A run may write to the same rows while this is working. Run it while no
extraction run is active; in any case every planned row is read again just
before writing, and a row whose status, stored answer or error changed since it
was first read is left as the run wrote it.

Nothing is projected here; the next projection run picks up the new items. The
``extraction_runs`` totals of the runs whose rows flip to ``succeeded`` are not
changed: they say what each run saw at the time. Every write goes through
:mod:`phases_v2.datasets.store`. A second run finds nothing to do: what passed
is no longer failed, and what is still invalid already carries its detailed
reason (with or without the attempt count a run adds).

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
from phases_v2.extraction.adapters.secondary.extraction_tool_schema import (
    UnknownOutput,
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
    is_failed_call,
)
from phases_v2.prompts.domain import PromptTemplate
from phases_v2.sql import in_list

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
NO_CONTRACT = "left as is: no output contract for the prompt's answer key"
CHANGED = "left as is: changed by a run since it was read"
NO_PROMPT = "left as is: prompt is not registered"
NO_CHUNK = "left as is: chunk no longer exists"
ID_MISMATCH = "left as is: extraction id does not match its chunk, model and prompt"
FAILED_CALL = "left as is: failed call whose kept answer is still invalid"


_GAVE_UP = re.compile(r" \(gave up after \d+ attempts\)$")


def _without_attempts(error: str) -> str:
    """``error`` without the attempt count a run appends when it gives up."""
    return _GAVE_UP.sub("", error)


def reason(error: str | None) -> str:
    """``error`` reduced to its first problem, without positions or sizes.

    Groups the report: ``relations[3].evidence_text: length 630 exceeds 500``
    and ``relations[0].evidence_text: length 510 exceeds 500`` are one reason.
    """
    if not error:
        return "(no error)"
    text = _without_attempts(error)
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
class _Entry:
    """What one stored failed answer becomes."""

    failed: _Failed
    kind: str
    # The row to write, and the items to write before it; None and [] when
    # the row is left as it is.
    extraction: ExtractionRecord | None = None
    items: list[ExtractedItemRecord] = field(default_factory=list)
    # The reason the report counts it under afterwards.
    after: str = ""


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
            CHANGED,
            NOT_A_MESSAGE,
            NO_CONTRACT,
            NO_PROMPT,
            NO_CHUNK,
            ID_MISMATCH,
            FAILED_CALL,
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
    except UnknownOutput:
        return NO_CONTRACT, None
    except (InvalidAnswer, UnusableResponse) as failure:
        if is_failed_call(record.raw_response, record.error):
            # The chunk never got its answers: rewriting the error with the
            # kept answer's reason would count it as an invalid answer.
            return FAILED_CALL, None
        error = str(failure)
        # A run stores the same reason followed by its attempt count; that
        # count is kept.
        stored = record.error or ""
        if error in (stored, _without_attempts(stored)):
            return UNCHANGED, None
        return REWRITTEN, error

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


def _plan(rows: DatasetRowStore, read: Reader) -> list[_Entry]:
    entries = []
    for failed in _failed_answers(rows):
        record = failed.record
        kind, detail = _recheck(failed, read)
        entry = _Entry(failed, kind, after=reason(record.error))
        if kind == ACCEPTED:
            entry.extraction, entry.items = detail
            entry.after = SUCCEEDED
        elif kind == REWRITTEN:
            entry.extraction = replace(record, error=detail)
            entry.after = reason(detail)
        entries.append(entry)
    return entries


def _drop_changed(rows: DatasetRowStore, entries: list[_Entry]) -> None:
    """Leave alone every planned row a run has written since it was read.

    Without this, a chunk a run extracted successfully while the re-check was
    reading would be put back to the stale ``failed`` row.
    """
    planned = {
        entry.failed.record.extraction_id: entry
        for entry in entries
        if entry.extraction is not None
    }
    ids = sorted(planned)
    current: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), _BATCH):
        for row in rows.query(
            "SELECT extraction_id, status, raw_response, error FROM extractions "
            f"WHERE extraction_id IN {in_list(ids[start : start + _BATCH])}"  # nosec B608 - in_list escapes every value
        ):
            current[row["extraction_id"]] = row
    for extraction_id, entry in planned.items():
        record = entry.failed.record
        now = current.get(extraction_id)
        if now is not None and (
            now["status"],
            now["raw_response"],
            now["error"],
        ) == (record.status, record.raw_response, record.error):
            continue
        entry.kind, entry.extraction, entry.items = CHANGED, None, []
        if now is None:
            entry.after = "(row deleted)"
        elif now["status"] == SUCCEEDED:
            entry.after = SUCCEEDED
        else:
            entry.after = reason(now["error"])


def _write(store: DatasetExtractionStore, entries: list[_Entry]) -> None:
    """Every item first, then the extraction rows that own them.

    The extraction row is what marks a chunk done, so a run that stops half
    way leaves the rest still failed, and a repeat picks them up.
    """
    items = [item for entry in entries for item in entry.items]
    extractions = [entry.extraction for entry in entries if entry.extraction]
    for start in range(0, len(items), _BATCH):
        store.save_items(items[start : start + _BATCH])
    for start in range(0, len(extractions), _BATCH):
        store.save_extractions(extractions[start : start + _BATCH])


def recheck(
    dataset: DatasetService,
    *,
    dry_run: bool = False,
    read: Reader = LangchainExtractionModel.reread,
) -> Report:
    rows = DatasetRowStore(dataset)
    without_answer = _without_answer(rows)
    entries = _plan(rows, read)
    _drop_changed(rows, entries)
    if not dry_run:
        _write(DatasetExtractionStore(rows), entries)

    before: Counter = Counter()
    after: Counter = Counter()
    for entry in entries:
        record = entry.failed.record
        before[(record.prompt_id, record.model_id, reason(record.error))] += 1
        after[(record.prompt_id, record.model_id, entry.after)] += 1
    return Report(
        dry_run=dry_run,
        before=before,
        after=after,
        outcomes=Counter(entry.kind for entry in entries),
        items=sum(len(entry.items) for entry in entries),
        without_answer=without_answer,
    )


def main(engine: Any, argv: list[str]) -> Report:
    report = recheck(engine.services.dataset, dry_run="--dry-run" in argv)
    print(report.render(), flush=True)
    return report


if __name__ == "__main__":
    from phases_v2 import ABIModule

    main(ABIModule.get_instance().engine, sys.argv[1:])
