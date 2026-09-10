"""Running prompts against chunks, exactly once per chunk x model x prompt."""

import json

from phases_v2 import identity
from phases_v2.extraction.domain import run_extraction
from phases_v2.extraction.fakes import FakeExtractionStore, FakeModel
from phases_v2.extraction.interfaces import FAILED, SUCCEEDED, ChunkRef
from phases_v2.prompts.domain import PromptTemplate

PROMPT = PromptTemplate(
    name="claims", template="Find claims in {chunk_text}", output_key="results"
)


def _store(count=1):
    return FakeExtractionStore(
        [ChunkRef(f"c{i}", f"p{i}", f"chunk text {i}") for i in range(count)]
    )


def _run(store, model=None, **kwargs):
    return run_extraction(
        store=store,
        model=model or FakeModel(),
        prompt=PROMPT,
        model_id="openai/gpt-4.1-mini",
        chunker_id="chunker-a",
        **kwargs,
    )


# -- identity and dedup -------------------------------------------------


def test_an_extraction_is_identified_by_chunk_model_and_prompt():
    store = _store()

    _run(store)

    expected = identity.extraction_id("c0", "openai/gpt-4.1-mini", PROMPT.prompt_id)
    assert expected in store.extractions


def test_nothing_outstanding_makes_no_model_calls():
    store = _store()
    model = FakeModel()
    _run(store, model=model)
    calls_after_first = len(model.prompts)

    report = _run(store, model=model)

    assert len(model.prompts) == calls_after_first
    assert report.executed == 0
    assert report.skipped == 1


def test_editing_the_prompt_makes_every_chunk_outstanding_again():
    store = _store()
    _run(store)

    edited = PromptTemplate(
        name="claims", template="Find ALL claims in {chunk_text}", output_key="results"
    )
    report = run_extraction(
        store=store,
        model=FakeModel(),
        prompt=edited,
        model_id="openai/gpt-4.1-mini",
        chunker_id="chunker-a",
    )

    assert report.succeeded == 1
    assert len(store.extractions) == 2


def test_extractions_under_the_previous_prompt_survive():
    store = _store()
    _run(store)
    before = identity.extraction_id("c0", "openai/gpt-4.1-mini", PROMPT.prompt_id)

    run_extraction(
        store=store,
        model=FakeModel(),
        prompt=PromptTemplate(
            name="claims", template="Different {chunk_text}", output_key="results"
        ),
        model_id="openai/gpt-4.1-mini",
        chunker_id="chunker-a",
    )

    assert store.extractions[before].status == SUCCEEDED


def test_a_new_chunk_is_the_only_outstanding_work():
    store = _store()
    _run(store)
    store.add_chunk(ChunkRef("c9", "p9", "new chunk"))

    report = _run(store)

    assert report.succeeded == 1
    assert report.skipped == 1


def test_a_failed_attempt_is_retried_on_the_next_run():
    store = _store()
    _run(store, model=FakeModel(fail_on={"chunk text 0"}))
    assert store.extractions[list(store.extractions)[0]].status == FAILED

    report = _run(store)

    assert report.succeeded == 1


# -- results ------------------------------------------------------------


def test_a_success_records_the_response_and_the_item_count():
    store = _store()

    _run(store, model=FakeModel(json.dumps({"results": ["one", "two"]})))

    [record] = store.extractions.values()
    assert record.status == SUCCEEDED
    assert record.item_count == 2
    assert record.response == {"results": ["one", "two"]}
    assert record.error is None
    assert record.completed_at is not None


def test_items_are_recorded_one_per_result_with_full_provenance():
    store = _store()

    _run(store, model=FakeModel(json.dumps({"results": ["one", "two"]})))

    items = sorted(store.items.values(), key=lambda i: i.seq)
    assert [item.text for item in items] == ["one", "two"]
    for item in items:
        assert item.chunk_id == "c0"
        assert item.paper_id == "p0"
        assert item.prompt_id == PROMPT.prompt_id


def test_a_zero_item_success_is_a_success_with_no_item_rows():
    store = _store()

    report = _run(store, model=FakeModel(json.dumps({"results": []})))

    assert report.succeeded == 1
    [record] = store.extractions.values()
    assert record.status == SUCCEEDED
    assert record.item_count == 0
    assert store.items == {}


def test_a_model_failure_is_recorded_with_its_reason():
    store = _store()

    report = _run(store, model=FakeModel(fail_on={"chunk text 0"}))

    assert report.failed == 1
    [record] = store.extractions.values()
    assert record.status == FAILED
    assert "refused" in record.error


def test_unparseable_output_is_a_failure_that_keeps_the_raw_response():
    store = _store()

    _run(store, model=FakeModel("not json at all"))

    [record] = store.extractions.values()
    assert record.status == FAILED
    # `response` is a JSON column and this was not JSON, so the verbatim text
    # is what survives — the case where re-parsing later matters most.
    assert record.response is None
    assert record.raw_response == "not json at all"


def test_output_missing_the_expected_key_is_a_failure():
    store = _store()

    _run(store, model=FakeModel(json.dumps({"other_key": ["x"]})))

    [record] = store.extractions.values()
    assert record.status == FAILED
    assert "results" in record.error


def test_one_failure_does_not_stop_the_others():
    store = _store(count=3)

    report = _run(store, model=FakeModel(fail_on={"chunk text 1"}))

    assert report.succeeded == 2
    assert report.failed == 1


def test_items_are_written_before_the_extraction_that_owns_them():
    # The extractions row is what dedup reads, so it is the commit point:
    # a crash between the two must leave the work outstanding, not leave a
    # successful extraction whose items were never written.
    store = _store()

    _run(store)

    assert store.write_order.index("items") < store.write_order.index("extractions")


# -- runs and scoping ---------------------------------------------------


def test_the_run_is_recorded_with_its_scope_and_counts():
    store = _store(count=3)

    report = _run(store, model=FakeModel(fail_on={"chunk text 2"}))

    [run] = store.runs.values()
    assert run.run_id == report.run_id
    assert run.chunker_id == "chunker-a"
    assert run.model_id == "openai/gpt-4.1-mini"
    assert run.prompt_id == PROMPT.prompt_id
    assert (run.succeeded, run.failed) == (2, 1)
    assert run.finished_at >= run.started_at


def test_a_run_can_be_limited_to_a_number_of_chunks():
    store = _store(count=5)

    report = _run(store, max_chunks=2)

    assert report.executed == 2


def test_a_run_can_be_scoped_to_a_subset_of_papers():
    store = _store(count=3)

    _run(store, paper_ids=["p1"])

    assert {r.chunk_id for r in store.extractions.values()} == {"c1"}


def test_skipped_counts_what_was_already_done_within_the_scope():
    store = _store(count=3)
    _run(store)

    report = _run(store)

    assert report.skipped == 3
    assert report.executed == 0


def test_model_validation_failure_keeps_raw_tool_message():
    from phases_v2.extraction.interfaces import ModelFailed

    class InvalidToolModel:
        def complete(self, prompt):
            raise ModelFailed("invalid tool schema", raw_response='{"tool_calls": []}')

    store = FakeExtractionStore([ChunkRef("c1", "p1", "text")])
    report = run_extraction(
        store=store,
        model=InvalidToolModel(),
        prompt=PROMPT,
        model_id="m",
        chunker_id="w1",
    )
    assert report.failed == 1
    [record] = store.extractions.values()
    assert record.raw_response == '{"tool_calls": []}'
