"""The re-check of stored failed answers, against a real local dataset catalog."""

from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2 import identity
from phases_v2.datasets import store
from phases_v2.datasets.schemas import NAMESPACE
from phases_v2.extraction.adapters.secondary.LangchainExtractionModel import (
    LangchainExtractionModel,
)
from phases_v2.extraction.domain import run_extraction
from phases_v2.extraction.fakes import FakeExtractionStore
from phases_v2.extraction.interfaces import ChunkRef
from phases_v2.migrations.recheck_failed_extractions import reason, recheck
from phases_v2.prompts.domain import PromptTemplate
from phases_v2.prompts.templates import declared_prompts

PROMPTS = {prompt.name: prompt for prompt in declared_prompts()}
RELATIONS = PROMPTS["probabilistic_processes"]
STATEMENTS = next(
    prompt
    for prompt in declared_prompts()
    if prompt.name == "conditional_statement"
    and prompt.prompt_id == "conditional_statement_06c299d1b873"
)
GPT = "openai/gpt-4.1-mini"
SONNET = "openrouter/claude-sonnet-4.6"
WHEN = datetime(2026, 9, 19, 8, 30, tzinfo=UTC)
OLD_ERROR = "extraction tool call failed: invalid RelationsOutput"

RELATION = {
    "subject_process": "spending time alone",
    "subject_participant": "older adults",
    "target_process": "feeling calm",
    "direction": "increases",
    "evidence_text": "Older adults who spent time alone reported feeling calmer.",
}
LONG = RELATION | {"evidence_text": "x" * 217}
ALTERS = RELATION | {"direction": "alters"}

_TABLES = ("prompts", "chunks", "extractions", "extracted_items")


def _message(args) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "submit_extraction", "args": args, "id": "call-1"}],
    )


@pytest.fixture(scope="module")
def catalog(tmp_path_factory) -> DatasetService:
    root = tmp_path_factory.mktemp("recheck")
    service = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{root / 'catalog.sqlite'}",
            data_path=str(root / "data") + "/",
        )
    )
    store.ensure_datasets(service)
    return service


@pytest.fixture
def dataset(catalog) -> DatasetService:
    for table in _TABLES:
        store.truncate(catalog, table)
    return catalog


def _chunk(chunk_id: str) -> ChunkRef:
    return ChunkRef(chunk_id=chunk_id, paper_id=f"paper-{chunk_id}", text="text")


def _failed(chunk, model, prompt, *, args=None, error=OLD_ERROR, run="run-1"):
    raw = _message(args).model_dump_json() if args is not None else None
    return {
        "extraction_id": identity.extraction_id(chunk, model, prompt.prompt_id),
        "chunk_id": chunk,
        "model_id": model,
        "prompt_id": prompt.prompt_id,
        "run_id": run,
        "status": "failed",
        "response": None,
        "raw_response": raw,
        "error": error,
        "item_count": 0,
        "completed_at": WHEN,
    }


ROWS = {
    "long evidence": ("c1", GPT, RELATIONS, {"relations": [RELATION, LONG]}),
    "eleven statements": (
        "c2",
        SONNET,
        STATEMENTS,
        {"conditional_statement": [f"If {n}, then more." for n in range(11)]},
    ),
    "alters": ("c3", GPT, RELATIONS, {"relations": [ALTERS]}),
}


@pytest.fixture
def seeded(dataset):
    store.write_rows(
        dataset,
        "prompts",
        [
            {
                "prompt_id": prompt.prompt_id,
                "name": prompt.name,
                "prompt_sha256": identity.prompt_sha256(prompt.template),
                "template": prompt.template,
                "output_key": prompt.output_key,
                "registered_at": WHEN,
            }
            for prompt in (RELATIONS, STATEMENTS)
        ],
    )
    store.write_rows(
        dataset,
        "chunks",
        [
            {
                "chunk_id": chunk,
                "paper_id": f"paper-{chunk}",
                "chunker_id": "window",
                "seq": 0,
                "text": "text",
            }
            for chunk in ("c1", "c2", "c3", "c4", "c5")
        ],
    )
    store.write_rows(
        dataset,
        "extractions",
        [
            _failed(chunk, model, prompt, args=args, run=f"run-{label}")
            for label, (chunk, model, prompt, args) in ROWS.items()
        ]
        + [
            # A failed call: the model never answered.
            _failed("c4", GPT, RELATIONS, error="Connection error."),
            # Already re-checked: the stored error is the detailed one.
            _failed(
                "c5",
                GPT,
                RELATIONS,
                args={"relations": [ALTERS]},
                error=(
                    "invalid RelationsOutput: relations[0].direction: 'alters' is "
                    "not one of increases, decreases, no-effect"
                ),
            ),
        ],
    )
    return dataset


def _rows(dataset, table, key):
    return sorted(
        dataset.query(f"SELECT * FROM {table}", namespace=NAMESPACE).rows,
        key=lambda row: row[key],
    )


def _extraction(dataset, chunk):
    [row] = [
        row
        for row in dataset.query(
            f"SELECT * FROM extractions WHERE chunk_id = '{chunk}'",
            namespace=NAMESPACE,
        ).rows
    ]
    return row


def _live(chunk, model, prompt, args):
    """The rows a live run writes when the model gives this answer."""

    class _Chat:
        def bind_tools(self, tools, **kwargs):
            return self

        def invoke(self, text):
            return _message(args)

    live = FakeExtractionStore([_chunk(chunk)])
    run_extraction(
        store=live,
        model=LangchainExtractionModel(_Chat(), prompt.output_key),
        prompt=prompt,
        model_id=model,
        chunker_id="window",
    )
    return live


@pytest.mark.parametrize("label", ["long evidence", "eleven statements"])
def test_an_answer_now_accepted_is_written_as_a_live_run_would(seeded, label):
    chunk, model, prompt, args = ROWS[label]
    before = _extraction(seeded, chunk)

    report = recheck(seeded)

    live = _live(chunk, model, prompt, args)
    [expected] = live.extractions.values()
    row = _extraction(seeded, chunk)
    assert row["extraction_id"] == expected.extraction_id
    assert row["status"] == "succeeded"
    assert row["error"] is None
    assert row["response"] == expected.response
    assert row["raw_response"] == expected.raw_response
    assert row["item_count"] == expected.item_count == len(next(iter(args.values())))
    # The answer came from the original call.
    assert row["run_id"] == before["run_id"] == f"run-{label}"
    assert row["completed_at"] == before["completed_at"]

    items = [
        item
        for item in _rows(seeded, "extracted_items", "item_id")
        if item["chunk_id"] == chunk
    ]
    assert sorted(items, key=lambda item: item["seq"]) == [
        {
            "item_id": item.item_id,
            "extraction_id": item.extraction_id,
            "chunk_id": item.chunk_id,
            "paper_id": item.paper_id,
            "prompt_id": item.prompt_id,
            "seq": item.seq,
            "text": item.text,
        }
        for item in sorted(live.items.values(), key=lambda item: item.seq)
    ]
    assert report.outcomes["now accepted"] == 2


def test_an_answer_still_invalid_stays_failed_with_the_detailed_reason(seeded):
    before = _extraction(seeded, "c3")

    recheck(seeded)

    row = _extraction(seeded, "c3")
    assert row["status"] == "failed"
    assert row["error"] == (
        "invalid RelationsOutput: relations[0].direction: 'alters' is not one of "
        "increases, decreases, no-effect"
    )
    assert row["raw_response"] == before["raw_response"]
    assert row["response"] is None
    assert row["run_id"] == before["run_id"]
    assert row["completed_at"] == before["completed_at"]


def test_failed_calls_without_an_answer_and_unchanged_reasons_are_untouched(seeded):
    before = {chunk: _extraction(seeded, chunk) for chunk in ("c4", "c5")}

    report = recheck(seeded)

    assert {chunk: _extraction(seeded, chunk) for chunk in ("c4", "c5")} == before
    assert report.without_answer == 1
    assert report.outcomes["still invalid, reason unchanged"] == 1
    assert report.outcomes["still invalid, reason rewritten"] == 1


def test_a_dry_run_writes_nothing_and_says_what_a_real_run_would_do(seeded):
    before = {
        table: _rows(seeded, table, key)
        for table, key in (
            ("extractions", "extraction_id"),
            ("extracted_items", "item_id"),
        )
    }

    dry = recheck(seeded, dry_run=True)

    after = {
        table: _rows(seeded, table, key)
        for table, key in (
            ("extractions", "extraction_id"),
            ("extracted_items", "item_id"),
        )
    }
    assert after == before
    assert dry.outcomes["now accepted"] == 2
    assert dry.items == 2 + 11
    assert "dry run" in dry.render()
    real = recheck(seeded)
    assert (real.before, real.after, real.outcomes) == (
        dry.before,
        dry.after,
        dry.outcomes,
    )


def test_a_second_run_finds_nothing_to_do(seeded):
    recheck(seeded)
    extractions = _rows(seeded, "extractions", "extraction_id")
    items = _rows(seeded, "extracted_items", "item_id")

    again = recheck(seeded)

    assert again.changed == 0
    assert again.items == 0
    assert "nothing to do" in again.render()
    assert _rows(seeded, "extractions", "extraction_id") == extractions
    assert _rows(seeded, "extracted_items", "item_id") == items


def test_counts_are_reported_by_prompt_model_and_reason(seeded):
    report = recheck(seeded)

    relations = RELATIONS.prompt_id
    assert report.before[(relations, GPT, OLD_ERROR)] == 2
    assert report.after[(relations, GPT, "succeeded")] == 1
    assert report.after[(STATEMENTS.prompt_id, SONNET, "succeeded")] == 1
    alters = (
        "invalid RelationsOutput: relations[].direction: 'alters' is not one of "
        "increases, decreases, no-effect"
    )
    assert report.after[(relations, GPT, alters)] == 2
    rendered = report.render()
    assert relations in rendered and SONNET in rendered
    assert "now accepted: 2" in rendered


def _register(dataset, *prompts):
    store.write_rows(
        dataset,
        "prompts",
        [
            {
                "prompt_id": prompt.prompt_id,
                "name": prompt.name,
                "prompt_sha256": identity.prompt_sha256(prompt.template),
                "template": prompt.template,
                "output_key": prompt.output_key,
                "registered_at": WHEN,
            }
            for prompt in prompts
        ],
    )


@pytest.mark.parametrize(
    "stored",
    [
        "Sorry, I cannot help with that.",
        '{"relations": [{"direction": "increases"}]}',
        "[]",
        "null",
    ],
)
def test_a_stored_answer_that_is_not_a_tool_call_is_left_as_it_is(dataset, stored):
    _register(dataset, RELATIONS)
    row = _failed("c9", GPT, RELATIONS, args={"relations": []}) | {
        "raw_response": stored
    }
    store.write_rows(dataset, "extractions", [row])

    dry = recheck(dataset, dry_run=True)
    report = recheck(dataset)

    row = _extraction(dataset, "c9")
    assert (row["status"], row["raw_response"], row["error"]) == (
        "failed",
        stored,
        OLD_ERROR,
    )
    for result in (dry, report):
        assert result.changed == 0
        assert (
            result.outcomes["left as is: stored answer is not a tool-call message"] == 1
        )


def test_a_prompt_with_no_output_contract_is_left_as_it_is(dataset):
    mystery = PromptTemplate("mystery", "Find {chunk_text}", "no_such_key")
    _register(dataset, mystery)
    store.write_rows(
        dataset,
        "extractions",
        [_failed("c9", GPT, mystery, args={"no_such_key": ["x"]})],
    )

    report = recheck(dataset)

    assert _extraction(dataset, "c9")["error"] == OLD_ERROR
    assert report.changed == 0
    assert (
        report.outcomes["left as is: no output contract for the prompt's answer key"]
        == 1
    )


def test_a_reason_stored_with_its_attempt_count_is_kept(dataset):
    _register(dataset, RELATIONS)
    stored = (
        "invalid RelationsOutput: relations[0].direction: 'alters' is not one of "
        "increases, decreases, no-effect (gave up after 3 attempts)"
    )
    store.write_rows(
        dataset,
        "extractions",
        [_failed("c9", GPT, RELATIONS, args={"relations": [ALTERS]}, error=stored)],
    )

    report = recheck(dataset)

    assert _extraction(dataset, "c9")["error"] == stored
    assert report.changed == 0
    assert report.outcomes["still invalid, reason unchanged"] == 1
    assert "nothing to do" in report.render()


def test_a_row_a_run_writes_while_the_recheck_reads_is_left_as_the_run_wrote_it(
    seeded,
):
    chunk, model, prompt, _ = ROWS["long evidence"]
    newer = _failed(chunk, model, prompt) | {
        "run_id": "run-newer",
        "status": "succeeded",
        "response": {"relations": [RELATION]},
        "raw_response": '{"relations": []}',
        "error": None,
        "item_count": 1,
    }
    done = []

    def read_while_a_run_succeeds(raw, output_key):
        # The run finishes this chunk after the re-check took its list of
        # failed rows, and before it writes.
        if not done:
            store.write_rows(seeded, "extractions", [newer])
            done.append(True)
        return LangchainExtractionModel.reread(raw, output_key)

    report = recheck(seeded, read=read_while_a_run_succeeds)

    row = _extraction(seeded, chunk)
    assert (row["status"], row["run_id"]) == ("succeeded", "run-newer")
    assert not [
        item
        for item in _rows(seeded, "extracted_items", "item_id")
        if item["chunk_id"] == chunk
    ]
    assert report.outcomes["left as is: changed by a run since it was read"] == 1
    # The rest went ahead.
    assert _extraction(seeded, "c2")["status"] == "succeeded"
    assert report.outcomes["now accepted"] == 1


@pytest.mark.parametrize(
    ("error", "grouped"),
    [
        (OLD_ERROR, OLD_ERROR),
        (
            "invalid RelationsOutput: relations[3].evidence_text: length 612 "
            "exceeds 500; relations[4].direction: 'x' is not one of a, b",
            "invalid RelationsOutput: relations[].evidence_text: length N exceeds 500",
        ),
        (
            "invalid WhatOutput: what: 31 items exceed 30 (gave up after 3 attempts)",
            "invalid WhatOutput: what: N items exceed 30",
        ),
        (None, "(no error)"),
    ],
)
def test_reasons_are_grouped_without_positions_or_sizes(error, grouped):
    assert reason(error) == grouped
