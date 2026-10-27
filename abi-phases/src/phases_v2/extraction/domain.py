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
import random
import time
import uuid
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime

from phases_v2 import identity
from phases_v2.extraction.interfaces import (
    FAILED,
    LEGACY_OUTPUT_KEYS,
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


@dataclass(frozen=True)
class RetryPolicy:
    """How hard to try a call that failed for a reason that may pass.

    Applies only to failures the model adapter marks transient — a dropped
    connection, a timeout, a rate limit, a provider 5xx. Unusable output is
    never retried: it is recorded as failed with its reason, so the cost of a
    prompt that does not produce valid output stays one call per chunk.
    """

    max_attempts: int = 5
    base_delay: float = 2.0
    max_delay: float = 60.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("delays must not be negative")

    def delay_before_retry(self, attempt: int) -> float:
        """Seconds to wait after the ``attempt``-th failure.

        Exponential, capped, with the upper half jittered so the workers of
        one run do not all come back in the same instant after a shared outage.
        """
        ceiling = min(self.max_delay, self.base_delay * 2 ** (attempt - 1))
        return ceiling * random.uniform(0.5, 1.0)  # nosec B311 - not security


DEFAULT_RETRY = RetryPolicy()


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
        output_key = next(
            (key for key in LEGACY_OUTPUT_KEYS.get(output_key, ()) if key in parsed),
            output_key,
        )
    if output_key not in parsed:
        raise UnusableResponse(
            f"response has no {output_key!r} key; keys were "
            f"{', '.join(sorted(map(str, parsed))) or '(none)'}"
        )

    items = parsed[output_key]
    if not isinstance(items, list):
        raise UnusableResponse(f"{output_key!r} was not a list")
    return parsed, [
        json.dumps(item, ensure_ascii=False)
        if isinstance(item, (dict, list))
        else str(item)
        for item in items
    ]


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
    workers: int = 20,
    retry: RetryPolicy = DEFAULT_RETRY,
    sleep: Callable[[float], None] = time.sleep,
) -> ExtractionReport:
    """Extract from every chunk that has no succeeded extraction yet.

    A call that fails transiently is retried per ``retry`` before the chunk is
    recorded as failed; ``sleep`` is injectable so tests need not wait.

    ``run_id`` may be supplied so a caller that already has an identity for the
    work — a run request, say — can find this run's counts later by that id
    rather than guessing which of several runs was theirs.
    """
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError("workers must be a positive integer")
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

    # Only model calls run in workers. Persist and update counts on this thread.
    chunks = iter(outstanding)
    with ThreadPoolExecutor(max_workers=workers) as pool:

        def submit(chunk):
            return pool.submit(
                _extract_one,
                chunk,
                model=model,
                prompt=prompt,
                model_id=model_id,
                run_id=run_id,
                retry=retry,
                sleep=sleep,
            )

        pending = {submit(chunk) for chunk in outstanding[:workers]}
        for _ in range(min(workers, len(outstanding))):
            next(chunks)
        try:
            while pending:
                completed, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in completed:
                    record, items = future.result()
                    _save(store, record, items=items)
                    if record.status == FAILED:
                        report.failed += 1
                        report.errors[record.chunk_id] = (
                            record.error or "extraction failed"
                        )
                    else:
                        report.succeeded += 1
                for _ in completed:
                    chunk = next(chunks, None)
                    if chunk is not None:
                        pending.add(submit(chunk))
        finally:
            for future in pending:
                future.cancel()

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
    model: ExtractionModel,
    prompt: PromptTemplate,
    model_id: str,
    run_id: str,
    retry: RetryPolicy,
    sleep: Callable[[float], None],
) -> tuple[ExtractionRecord, list[ExtractedItemRecord]]:
    extraction_id = identity.extraction_id(chunk.chunk_id, model_id, prompt.prompt_id)
    raw: str | None = None

    try:
        raw = _complete_with_retry(
            model, prompt.rendered_for(chunk.text), retry=retry, sleep=sleep
        )
        response, items = parse_items(raw, prompt.output_key)
    except (ModelFailed, UnusableResponse) as failure:
        if isinstance(failure, ModelFailed):
            raw = failure.raw_response
        return (
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
            [],
        )

    return (
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
        [
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


def _complete_with_retry(
    model: ExtractionModel,
    prompt: str,
    *,
    retry: RetryPolicy,
    sleep: Callable[[float], None],
) -> str:
    """Call the model, retrying only failures it says are transient.

    The last failure is re-raised with the attempt count in its message, so a
    chunk that stays failed says it was not for want of trying.
    """
    attempt = 1
    while True:
        try:
            return model.complete(prompt)
        except ModelFailed as failure:
            if not failure.transient or attempt >= retry.max_attempts:
                if attempt > 1:
                    raise ModelFailed(
                        f"{failure} (gave up after {attempt} attempts)",
                        raw_response=failure.raw_response,
                        transient=failure.transient,
                    ) from failure
                raise
            sleep(retry.delay_before_retry(attempt))
            attempt += 1


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
