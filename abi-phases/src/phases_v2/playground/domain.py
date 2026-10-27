"""Trying a prompt on a few chunks of one paper, without running the pipeline.

A try sends each chunk through :func:`phases_v2.extraction.domain.attempt`, the
same rendering and parsing a pipeline run uses, so what a user sees here is what
a run would record. Nothing is written: no prompt, extraction, item, run or
projection. Saving the draft is a separate, explicit step.

The answer comes back in the same HTTP request, so the work is bounded three
ways: at most :data:`MAX_CHUNKS` chunks, a few model calls at once, and an
overall deadline after which unfinished chunks are reported as timed out.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait

from phases_v2 import identity
from phases_v2.extraction.domain import Attempt, attempt
from phases_v2.extraction.interfaces import FAILED, SUCCEEDED
from phases_v2.models.catalog import UnknownModelError
from phases_v2.models.catalog import resolve as resolve_model
from phases_v2.playground.interfaces import (
    NOT_RUN,
    TIMED_OUT,
    BaselineChunk,
    ChunkTry,
    ModelFactory,
    PaperChunk,
    PlaygroundStore,
    StoredExtraction,
    TryReport,
)
from phases_v2.prompts.domain import CHUNK_PLACEHOLDER, PromptTemplate
from phases_v2.structured_text import canonical_payload_text

logger = logging.getLogger(__name__)

MAX_CHUNKS = 10
DEFAULT_FIRST = 3
#: Output keys whose items are objects rather than sentences.
STRUCTURED_KEYS = frozenset({"relations"})


class TryRefused(ValueError):
    """The try cannot run as asked; the message says what to change."""


def check_request(
    *, has_prompt_id: bool, has_draft: bool, seq_count: int, template: str | None
) -> None:
    """The refusals users meet most, in plain words.

    Run by :func:`try_prompt`, and by the HTTP layer before the contract's
    field-by-field validation, so both say the same thing.
    """
    if has_prompt_id == has_draft:
        raise TryRefused(
            "Try one thing at a time: either a draft or a saved prompt version."
        )
    if seq_count > MAX_CHUNKS:
        raise TryRefused(
            f"Try at most {MAX_CHUNKS} chunks at a time; {seq_count} were chosen."
        )
    if template is not None and CHUNK_PLACEHOLDER not in template:
        raise TryRefused(
            "The prompt text must contain {chunk_text}, where each chunk's "
            "text is placed."
        )


def present_items(texts: list[str], output_key: str) -> list[object]:
    """Items as a reader should see them: relations as objects, claims as text."""
    if output_key not in STRUCTURED_KEYS:
        return list(texts)
    shown: list[object] = []
    for text in texts:
        try:
            shown.append(json.loads(canonical_payload_text(text)))
        except ValueError:
            shown.append(text)
    return shown


def try_prompt(
    *,
    store: PlaygroundStore,
    model_factory: ModelFactory,
    model_id: str,
    paper_id: str,
    chunker_id: str,
    prompt_id: str | None = None,
    draft: PromptTemplate | None = None,
    seqs: list[int] | None = None,
    first: int | None = None,
    baseline_prompt_id: str | None = None,
    is_model_available: Callable[[str], bool] | None = None,
    workers: int = 4,
    timeout_seconds: float = 90.0,
    clock: Callable[[], float] = time.monotonic,
) -> TryReport:
    """Run one prompt version or draft on up to ten chunks of one paper."""
    started = clock()
    check_request(
        has_prompt_id=prompt_id is not None,
        has_draft=draft is not None,
        seq_count=len(set(seqs or [])),
        template=draft.template if draft is not None else None,
    )
    prompt = _prompt(store, prompt_id, draft)
    _check_model(model_id, is_model_available)
    baseline = _baseline(store, baseline_prompt_id)
    chunks = _chunks(store, paper_id, chunker_id, seqs, first)

    try:
        model = model_factory(model_id, prompt.output_key)
    except Exception as failure:
        logger.exception("Could not build model %s for a prompt try", model_id)
        raise TryRefused(
            f"The model {model_id} could not be started on this deployment: {failure}"
        ) from failure

    tries, timed_out = _run(model, prompt, chunks, workers, timeout_seconds, clock)

    if baseline is not None:
        stored = store.stored(
            [chunk.chunk_id for chunk in chunks],
            model_id=model_id,
            prompt_id=baseline.prompt_id,
        )
        for chunk_try in tries:
            chunk_try.baseline = _baseline_chunk(
                stored.get(chunk_try.chunk_id), baseline.output_key
            )

    return TryReport(
        prompt_id=prompt.prompt_id,
        name=prompt.name,
        output_key=prompt.output_key,
        model_id=model_id,
        paper_id=paper_id,
        chunker_id=chunker_id,
        baseline_prompt_id=baseline.prompt_id if baseline else None,
        baseline_output_key=baseline.output_key if baseline else None,
        chunks=tries,
        elapsed_ms=_ms(clock() - started),
        timed_out=timed_out,
    )


# -- checks, all before any model call ----------------------------------------


def _prompt(
    store: PlaygroundStore, prompt_id: str | None, draft: PromptTemplate | None
) -> PromptTemplate:
    if draft is not None:
        return draft
    found = store.prompt(prompt_id or "")
    if found is None:
        raise TryRefused(
            f"Prompt version {prompt_id} was not found. Reload the prompt library."
        )
    return found


def _check_model(
    model_id: str, is_model_available: Callable[[str], bool] | None
) -> None:
    try:
        resolve_model(model_id)
    except UnknownModelError as unknown:
        raise TryRefused(f"Unknown model {model_id}. Choose a listed model.") from (
            unknown
        )
    if is_model_available is not None and not is_model_available(model_id):
        raise TryRefused(f"The model {model_id} is unavailable on this deployment.")


def _baseline(
    store: PlaygroundStore, baseline_prompt_id: str | None
) -> PromptTemplate | None:
    if not baseline_prompt_id:
        return None
    found = store.prompt(baseline_prompt_id)
    if found is None:
        raise TryRefused(
            f"Baseline version {baseline_prompt_id} was not found. Choose another."
        )
    return found


def _chunks(
    store: PlaygroundStore,
    paper_id: str,
    chunker_id: str,
    seqs: list[int] | None,
    first: int | None,
) -> list[PaperChunk]:
    seqs = list(dict.fromkeys(seqs or []))
    if not seqs:
        first = DEFAULT_FIRST if first is None else first
        if not 1 <= first <= MAX_CHUNKS:
            raise TryRefused(
                f"Try between 1 and {MAX_CHUNKS} chunks at a time; {first} were asked for."
            )
    if not store.is_ingested(paper_id):
        raise TryRefused(
            "That paper has not been ingested. Choose a paper from the library."
        )
    counts = store.chunk_counts(paper_id)
    if not counts.get(chunker_id):
        cut_with = ", ".join(sorted(counts)) or "no chunker yet"
        raise TryRefused(
            f"This paper has not been chunked with {chunker_id} (it is chunked with "
            f"{cut_with}). Choose that chunker, or run the pipeline on the paper first."
        )

    if seqs:
        found = store.chunks(paper_id, chunker_id, seqs=seqs)
        missing = sorted(set(seqs) - {chunk.seq for chunk in found})
        if missing:
            raise TryRefused(
                f"This paper has no chunk {', '.join(map(str, missing))} with "
                f"{chunker_id}; its chunks are numbered 0 to {counts[chunker_id] - 1}."
            )
        return found
    return store.chunks(paper_id, chunker_id, first=first)


# -- the calls -----------------------------------------------------------------


def _run(
    model,
    prompt: PromptTemplate,
    chunks: list[PaperChunk],
    workers: int,
    timeout_seconds: float,
    clock: Callable[[], float],
) -> tuple[list[ChunkTry], bool]:
    def timed(chunk: PaperChunk) -> tuple[Attempt, int]:
        began = clock()
        outcome = attempt(model, prompt, chunk.text)
        return outcome, _ms(clock() - began)

    pool = ThreadPoolExecutor(max_workers=max(1, min(workers, len(chunks))))
    try:
        futures = [pool.submit(timed, chunk) for chunk in chunks]
        done, _ = wait(futures, timeout=timeout_seconds)
    finally:
        # Calls still running cannot be interrupted; they finish in the
        # background and their answers are dropped. Queued ones never start.
        pool.shutdown(wait=False, cancel_futures=True)

    tries = []
    for chunk, future in zip(chunks, futures):
        if future not in done:
            tries.append(
                _chunk_try(
                    chunk,
                    status=TIMED_OUT,
                    error=(
                        f"No answer within {timeout_seconds:g} seconds. Try fewer "
                        "chunks, or a faster model."
                    ),
                    elapsed_ms=_ms(timeout_seconds),
                )
            )
            continue
        try:
            outcome, elapsed_ms = future.result()
        except Exception as failure:  # noqa: BLE001 - one chunk, reported in place
            logger.exception("A prompt try failed on chunk %s", chunk.chunk_id)
            tries.append(
                _chunk_try(chunk, status=FAILED, error=str(failure), elapsed_ms=0)
            )
            continue
        tries.append(
            _chunk_try(
                chunk,
                status=outcome.status,
                items=present_items(outcome.items, prompt.output_key),
                error=outcome.error,
                raw_output=outcome.raw if outcome.status != SUCCEEDED else None,
                elapsed_ms=elapsed_ms,
            )
        )
    return tries, len(done) < len(futures)


def _chunk_try(
    chunk: PaperChunk,
    *,
    status: str,
    items: list[object] | None = None,
    error: str | None = None,
    raw_output: str | None = None,
    elapsed_ms: int,
) -> ChunkTry:
    return ChunkTry(
        seq=chunk.seq,
        chunk_id=chunk.chunk_id,
        text=chunk.text,
        status=status,
        items=items or [],
        error=error,
        raw_output=raw_output,
        elapsed_ms=elapsed_ms,
    )


def _baseline_chunk(stored: StoredExtraction | None, output_key: str) -> BaselineChunk:
    if stored is None:
        return BaselineChunk(status=NOT_RUN)
    return BaselineChunk(
        status=stored.status,
        items=present_items(stored.items, output_key),
        error=stored.error,
    )


def _ms(seconds: float) -> int:
    return int(round(seconds * 1000))


def baseline_extraction_ids(
    chunk_ids: list[str], *, model_id: str, prompt_id: str
) -> list[str]:
    """The extraction ids a pipeline run gives these chunks: exact, not a search."""
    return [identity.extraction_id(c, model_id, prompt_id) for c in chunk_ids]
