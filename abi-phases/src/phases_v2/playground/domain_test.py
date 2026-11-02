"""Trying a prompt: what comes back per chunk, and what is refused."""

import json
import threading
import time

import pytest

from phases_v2.extraction.fakes import FakeModel
from phases_v2.extraction.interfaces import FAILED, SUCCEEDED, ModelFailed
from phases_v2.playground.domain import MAX_CHUNKS, TryRefused, try_prompt
from phases_v2.playground.fakes import BlockingModel, FakePlaygroundStore
from phases_v2.playground.interfaces import NOT_RUN, TIMED_OUT, StoredExtraction
from phases_v2.prompts.domain import PromptTemplate

MODEL = "openai/gpt-4.1-mini"
CHUNKER = "window_512_128"
SAVED = PromptTemplate("effects", "Saved: {chunk_text}", "effects")
DRAFT = PromptTemplate("effects", "Draft: {chunk_text}", "effects")


@pytest.fixture
def store():
    store = FakePlaygroundStore()
    store.add_prompt(SAVED)
    store.add_paper("paper-1", CHUNKER, [f"chunk text {i}" for i in range(15)])
    return store


def _try(store, model, **kwargs):
    kwargs.setdefault("draft", DRAFT)
    kwargs.setdefault("model_id", MODEL)
    kwargs.setdefault("paper_id", "paper-1")
    kwargs.setdefault("chunker_id", CHUNKER)
    built = []

    def factory(model_id, output_key):
        built.append((model_id, output_key))
        return model

    report = try_prompt(store=store, model_factory=factory, **kwargs)
    return report, built


def test_a_draft_is_rendered_per_chunk_and_its_items_come_back_in_seq_order(store):
    model = FakeModel(json.dumps({"effects": ["loneliness rises", "sleep falls"]}))

    report, built = _try(store, model, seqs=[4, 2])

    assert built == [(MODEL, "effects")]
    assert sorted(model.prompts) == ["Draft: chunk text 2", "Draft: chunk text 4"]
    assert [c.seq for c in report.chunks] == [2, 4]
    assert all(c.status == SUCCEEDED for c in report.chunks)
    assert report.chunks[0].items == ["loneliness rises", "sleep falls"]
    assert report.chunks[0].text == "chunk text 2"
    assert report.chunks[0].raw_output is None
    assert report.prompt_id == DRAFT.prompt_id
    assert report.timed_out is False


def test_without_chunk_positions_the_first_chunks_are_tried(store):
    report, _ = _try(store, FakeModel(json.dumps({"effects": []})), first=5)

    assert [c.seq for c in report.chunks] == [0, 1, 2, 3, 4]


def test_a_saved_version_is_tried_by_its_id(store):
    model = FakeModel(json.dumps({"effects": ["x"]}))

    report, _ = _try(store, model, draft=None, prompt_id=SAVED.prompt_id, first=1)

    assert model.prompts == ["Saved: chunk text 0"]
    assert report.prompt_id == SAVED.prompt_id


def test_a_model_failure_costs_one_chunk_and_keeps_the_raw_answer(store):
    class Flaky:
        def complete(self, prompt):
            if prompt.endswith(" 1"):
                raise ModelFailed("rate limited", raw_response='{"partial": true}')
            return json.dumps({"effects": ["fine"]})

    report, _ = _try(store, Flaky(), first=3)

    statuses = [c.status for c in report.chunks]
    assert statuses == [SUCCEEDED, FAILED, SUCCEEDED]
    failed = report.chunks[1]
    assert "rate limited" in failed.error
    assert failed.raw_output == '{"partial": true}'
    assert failed.items == []


def test_unparseable_output_is_reported_with_the_raw_text(store):
    report, _ = _try(store, FakeModel("this is not JSON"), first=1)

    chunk = report.chunks[0]
    assert chunk.status == FAILED
    assert "not JSON" in chunk.error
    assert chunk.raw_output == "this is not JSON"


def test_output_under_the_wrong_key_is_reported(store):
    report, _ = _try(store, FakeModel(json.dumps({"results": ["x"]})), first=1)

    assert report.chunks[0].status == FAILED
    assert "'effects'" in report.chunks[0].error


def test_an_unexpected_error_in_one_call_is_reported_on_that_chunk(store):
    class Broken:
        def complete(self, prompt):
            raise RuntimeError("socket closed")

    report, _ = _try(store, Broken(), first=2)

    assert [c.status for c in report.chunks] == [FAILED, FAILED]
    assert "socket closed" in report.chunks[0].error


def test_relations_come_back_as_structured_objects(store):
    relation = {
        "subject_process": "isolation",
        "subject_participant": "older adults",
        "target_process": "sleep",
        "direction": "decreases",
        "evidence_text": "isolation reduced sleep",
    }
    draft = PromptTemplate("rel", "R {chunk_text}", "relations")

    report, built = _try(
        store, FakeModel(json.dumps({"relations": [relation]})), draft=draft, first=1
    )

    assert built == [(MODEL, "relations")]
    assert report.chunks[0].items == [relation]


# -- the baseline ---------------------------------------------------------------


def test_the_baseline_shows_stored_items_failures_and_chunks_not_run_yet(store):
    chunks = store.paper_chunks[("paper-1", CHUNKER)]
    store.add_extraction(
        chunks[0].chunk_id,
        MODEL,
        SAVED.prompt_id,
        StoredExtraction(status=SUCCEEDED, error=None, items=["stored claim"]),
    )
    store.add_extraction(
        chunks[1].chunk_id,
        MODEL,
        SAVED.prompt_id,
        StoredExtraction(status=FAILED, error="timeout", items=[]),
    )
    # Same chunk and version, another model: not this baseline.
    store.add_extraction(
        chunks[2].chunk_id,
        "openai/gpt-5-mini",
        SAVED.prompt_id,
        StoredExtraction(status=SUCCEEDED, error=None, items=["other model"]),
    )

    report, _ = _try(
        store,
        FakeModel(json.dumps({"effects": ["new"]})),
        first=3,
        baseline_prompt_id=SAVED.prompt_id,
    )

    assert report.baseline_prompt_id == SAVED.prompt_id
    assert report.baseline_output_key == "effects"
    first, second, third = (c.baseline for c in report.chunks)
    assert (first.status, first.items) == (SUCCEEDED, ["stored claim"])
    assert (second.status, second.error) == (FAILED, "timeout")
    assert third.status == NOT_RUN


def test_stored_relations_in_the_baseline_are_structured_too(store):
    relations = PromptTemplate("rel", "Old {chunk_text}", "relations")
    store.add_prompt(relations)
    chunk = store.paper_chunks[("paper-1", CHUNKER)][0]
    stored = "{'subject_process': 'a', 'direction': 'increases'}"
    store.add_extraction(
        chunk.chunk_id,
        MODEL,
        relations.prompt_id,
        StoredExtraction(status=SUCCEEDED, error=None, items=[stored]),
    )

    report, _ = _try(
        store,
        FakeModel(json.dumps({"relations": []})),
        draft=PromptTemplate("rel", "New {chunk_text}", "relations"),
        first=1,
        baseline_prompt_id=relations.prompt_id,
    )

    assert report.chunks[0].baseline.items == [
        {"subject_process": "a", "direction": "increases"}
    ]


def test_without_a_baseline_none_is_looked_up(store):
    report, _ = _try(store, FakeModel(json.dumps({"effects": []})), first=1)

    assert report.baseline_prompt_id is None
    assert report.chunks[0].baseline is None


# -- refusals, all before any model call -----------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"seqs": list(range(MAX_CHUNKS + 1))}, "at most 10 chunks"),
        ({"first": MAX_CHUNKS + 1}, "between 1 and 10"),
        ({"first": 0}, "between 1 and 10"),
        ({"draft": PromptTemplate("x", "no placeholder", "effects")}, "{chunk_text}"),
        ({"model_id": "nobody/nothing"}, "Unknown model"),
        ({"paper_id": "missing"}, "has not been ingested"),
        ({"chunker_id": "window_1_x"}, "has not been chunked with window_1_x"),
        ({"seqs": [1, 40]}, "no chunk 40"),
        ({"draft": None, "prompt_id": "effects-unknown"}, "was not found"),
        ({"baseline_prompt_id": "effects-unknown"}, "Baseline version"),
        ({"prompt_id": SAVED.prompt_id}, "either a draft or a saved"),
    ],
)
def test_a_try_that_cannot_run_is_refused_before_calling_the_model(
    store, kwargs, message
):
    model = FakeModel()

    with pytest.raises(TryRefused, match=message.replace("{", r"\{")):
        _try(store, model, **kwargs)

    assert model.prompts == []


def test_a_model_this_deployment_cannot_build_is_refused(store):
    with pytest.raises(TryRefused, match="unavailable on this deployment"):
        _try(store, FakeModel(), is_model_available=lambda _: False)


def test_a_model_that_fails_to_start_is_refused_with_the_reason(store):
    def factory(model_id, output_key):
        raise RuntimeError("no API key configured")

    with pytest.raises(TryRefused, match="no API key configured"):
        try_prompt(
            store=store,
            model_factory=factory,
            model_id=MODEL,
            paper_id="paper-1",
            chunker_id=CHUNKER,
            draft=DRAFT,
        )


# -- bounds ------------------------------------------------------------------------


def test_calls_run_a_few_at_a_time():
    store = FakePlaygroundStore()
    store.add_paper("paper-1", CHUNKER, [f"t{i}" for i in range(10)])
    lock = threading.Lock()
    running = {"now": 0, "peak": 0}

    class Counting:
        def complete(self, prompt):
            with lock:
                running["now"] += 1
                running["peak"] = max(running["peak"], running["now"])
            time.sleep(0.02)
            with lock:
                running["now"] -= 1
            return json.dumps({"effects": []})

    report, _ = _try(store, Counting(), first=10, workers=3)

    assert len(report.chunks) == 10
    assert 1 < running["peak"] <= 3


def test_chunks_still_running_at_the_deadline_are_reported_as_timed_out(store):
    model = BlockingModel(json.dumps({"effects": ["late"]}))
    try:
        started = time.monotonic()
        report, _ = _try(store, model, first=2, timeout_seconds=0.05)
        assert time.monotonic() - started < 2
    finally:
        model.release.set()

    assert report.timed_out is True
    assert [c.status for c in report.chunks] == [TIMED_OUT, TIMED_OUT]
    assert "No answer within 0.05 seconds" in report.chunks[0].error
