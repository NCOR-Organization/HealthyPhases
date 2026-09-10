"""Running prompts against chunks, exactly once per chunk × model × prompt.

Two mechanisms keep that promise and they are not interchangeable. Upsert stops
duplicate *rows*; the outstanding-work query stops duplicate *work*. Without
the query an already-extracted chunk would still be sent to the model and would
merely overwrite its own row, having paid for the call.

Within one unit of work, items are written before the extraction row. The
extraction row is what the outstanding query reads, so it is the commit point:
a crash between the two leaves the work outstanding rather than leaving a
successful extraction whose items never arrived.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from phases_v2 import identity
from phases_v2.extraction.interfaces import (
    FAILED,
    SUCCEEDED,
    ChunkRef,
    ExtractedItemRecord,
    ExtractionModel,
    ExtractionRecord,
    ExtractionReport,
    ExtractionStore,
    ModelFailed,
    RunRecord,
)
from phases_v2.prompts.domain import PromptTemplate


class UnusableResponse(Exception):
    """The model answered, but not in a shape this prompt can use."""


def parse_items(raw: str, output_key: str) -> tuple[object, list[str]]:
    """Return ``(parsed_response, items)`` or raise :class:`UnusableResponse`.

    The raw response is kept whatever happens, so a parser fixed later can be
    re-run over stored output instead of paying for the calls again.
    """
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as failure:
        raise UnusableResponse(f"response was not JSON: {failure}") from failure

    if not isinstance(parsed, dict):
        raise UnusableResponse("response was not a JSON object")
    if output_key not in parsed:
        raise UnusableResponse(
            f"response has no {output_key!r} key; keys were "
            f"{', '.join(sorted(map(str, parsed))) or '(none)'}"
        )

    items = parsed[output_key]
    if not isinstance(items, list):
        raise UnusableResponse(f"{output_key!r} was not a list")
    return parsed, [str(item) for item in items]


def run_extraction(
    *,
    store: ExtractionStore,
    model: ExtractionModel,
    prompt: PromptTemplate,
    model_id: str,
    chunker_id: str,
    paper_ids: list[str] | None = None,
    max_chunks: int | None = None,
    run_id: str | None = None,
) -> ExtractionReport:
    """Extract from every chunk that has no succeeded extraction yet.

    ``run_id`` may be supplied so a caller that already has an identity for the
    work — a run request, say — can find this run's counts later by that id
    rather than guessing which of several runs was theirs.
    """
    run_id = run_id or str(uuid.uuid4())
    started_at = datetime.now(UTC)
    report = ExtractionReport(run_id=run_id)

    outstanding = store.outstanding_chunks(
        chunker_id=chunker_id,
        model_id=model_id,
        prompt_id=prompt.prompt_id,
        paper_ids=paper_ids,
        limit=max_chunks,
    )
    candidates = store.count_candidates(chunker_id=chunker_id, paper_ids=paper_ids)
    report.skipped = max(candidates - len(outstanding), 0)

    for chunk in outstanding:
        _extract_one(
            chunk,
            store=store,
            model=model,
            prompt=prompt,
            model_id=model_id,
            run_id=run_id,
            report=report,
        )

    store.save_run(
        RunRecord(
            run_id=run_id,
            chunker_id=chunker_id,
            model_id=model_id,
            prompt_id=prompt.prompt_id,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            succeeded=report.succeeded,
            failed=report.failed,
            skipped=report.skipped,
        )
    )
    return report


def _extract_one(
    chunk: ChunkRef,
    *,
    store: ExtractionStore,
    model: ExtractionModel,
    prompt: PromptTemplate,
    model_id: str,
    run_id: str,
    report: ExtractionReport,
) -> None:
    extraction_id = identity.extraction_id(chunk.chunk_id, model_id, prompt.prompt_id)
    raw: str | None = None

    try:
        raw = model.complete(prompt.rendered_for(chunk.text))
        response, items = parse_items(raw, prompt.output_key)
    except (ModelFailed, UnusableResponse) as failure:
        if isinstance(failure, ModelFailed):
            raw = failure.raw_response
        report.failed += 1
        report.errors[chunk.chunk_id] = str(failure)
        _save(
            store,
            _record(
                extraction_id,
                chunk,
                model_id,
                prompt,
                run_id,
                status=FAILED,
                # `response` is a JSON column, so unparseable output cannot go
                # there — but it is exactly the case where keeping the text
                # matters, so it goes to `raw_response` verbatim.
                response=None,
                raw=raw,
                error=str(failure),
                item_count=0,
            ),
            items=[],
        )
        return

    report.succeeded += 1
    _save(
        store,
        _record(
            extraction_id,
            chunk,
            model_id,
            prompt,
            run_id,
            status=SUCCEEDED,
            response=response,
            raw=raw,
            error=None,
            item_count=len(items),
        ),
        items=[
            ExtractedItemRecord(
                item_id=identity.item_id(extraction_id, seq),
                extraction_id=extraction_id,
                chunk_id=chunk.chunk_id,
                paper_id=chunk.paper_id,
                prompt_id=prompt.prompt_id,
                seq=seq,
                text=text,
            )
            for seq, text in enumerate(items)
        ],
    )


def _record(
    extraction_id: str,
    chunk: ChunkRef,
    model_id: str,
    prompt: PromptTemplate,
    run_id: str,
    *,
    status: str,
    response: object,
    raw: str | None,
    error: str | None,
    item_count: int,
) -> ExtractionRecord:
    return ExtractionRecord(
        extraction_id=extraction_id,
        chunk_id=chunk.chunk_id,
        model_id=model_id,
        prompt_id=prompt.prompt_id,
        run_id=run_id,
        status=status,
        response=response,
        raw_response=raw,
        error=error,
        item_count=item_count,
        completed_at=datetime.now(UTC),
    )


def _save(
    store: ExtractionStore,
    record: ExtractionRecord,
    *,
    items: list[ExtractedItemRecord],
) -> None:
    """Items first, then the extraction — see this module's docstring."""
    if items:
        store.save_items(items)
    store.save_extractions([record])
