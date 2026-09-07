"""The outstanding-work query, against a real dataset with seeded rows.

The domain tests use a fake whose dedup logic I wrote; this checks the SQL that
actually decides what gets sent to a model. Getting it wrong costs money in one
direction and silently drops work in the other.
"""

from datetime import UTC, datetime

import pytest
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2 import identity
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.store import ensure_datasets
from phases_v2.extraction.adapters.secondary.DatasetExtractionStore import (
    DatasetExtractionStore,
)
from phases_v2.extraction.interfaces import (
    FAILED,
    SUCCEEDED,
    ExtractionRecord,
)

CHUNKER = "window_1_abc"
MODEL = "openai/gpt-4.1-mini"
PROMPT = "claims_abc"


@pytest.fixture
def store(tmp_path):
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path / 'catalog.sqlite'}",
            data_path=str(tmp_path / "warehouse") + "/",
        )
    )
    ensure_datasets(dataset)
    rows = DatasetRowStore(dataset)
    rows.write_rows(
        "chunks",
        [
            {
                "chunk_id": f"c{i}",
                "paper_id": f"p{i % 2}",
                "chunker_id": CHUNKER,
                "seq": i,
                "text": f"chunk {i}",
            }
            for i in range(4)
        ],
    )
    # A chunk from a different mechanism must never be picked up.
    rows.write_rows(
        "chunks",
        [
            {
                "chunk_id": "other",
                "paper_id": "p0",
                "chunker_id": "window_2_zzz",
                "seq": 0,
                "text": "other mechanism",
            }
        ],
    )
    return DatasetExtractionStore(rows)


def _record(chunk_id, *, status, model=MODEL, prompt=PROMPT):
    extraction_id = identity.extraction_id(chunk_id, model, prompt)
    return ExtractionRecord(
        extraction_id=extraction_id,
        chunk_id=chunk_id,
        model_id=model,
        prompt_id=prompt,
        run_id="run-1",
        status=status,
        response={"results": []},
        raw_response='{"results": []}',
        error=None if status == SUCCEEDED else "boom",
        item_count=0,
        completed_at=datetime.now(UTC),
    )


def _outstanding(store, **kwargs):
    return [
        chunk.chunk_id
        for chunk in store.outstanding_chunks(
            chunker_id=CHUNKER, model_id=MODEL, prompt_id=PROMPT, **kwargs
        )
    ]


def test_everything_is_outstanding_before_any_extraction(store):
    assert _outstanding(store) == ["c0", "c1", "c2", "c3"]


def test_only_this_mechanisms_chunks_are_candidates(store):
    assert "other" not in _outstanding(store)


def test_a_succeeded_extraction_removes_its_chunk(store):
    store.save_extractions([_record("c0", status=SUCCEEDED)])

    assert _outstanding(store) == ["c1", "c2", "c3"]


def test_a_failed_extraction_leaves_its_chunk_outstanding(store):
    store.save_extractions([_record("c0", status=FAILED)])

    assert "c0" in _outstanding(store)


def test_a_success_under_a_different_model_does_not_count(store):
    store.save_extractions([_record("c0", status=SUCCEEDED, model="other/model")])

    assert "c0" in _outstanding(store)


def test_a_success_under_a_different_prompt_does_not_count(store):
    store.save_extractions([_record("c0", status=SUCCEEDED, prompt="other_prompt")])

    assert "c0" in _outstanding(store)


def test_nothing_is_outstanding_once_all_have_succeeded(store):
    store.save_extractions(
        [_record(f"c{i}", status=SUCCEEDED) for i in range(4)]
    )

    assert _outstanding(store) == []


def test_a_retry_that_succeeds_removes_the_chunk(store):
    store.save_extractions([_record("c0", status=FAILED)])
    store.save_extractions([_record("c0", status=SUCCEEDED)])

    assert "c0" not in _outstanding(store)


def test_the_scope_can_be_narrowed_to_papers(store):
    assert _outstanding(store, paper_ids=["p0"]) == ["c0", "c2"]


def test_scoping_to_no_papers_yields_nothing(store):
    assert _outstanding(store, paper_ids=[]) == []


def test_a_limit_caps_how_much_work_comes_back(store):
    assert _outstanding(store, limit=2) == ["c0", "c1"]


def test_a_hostile_paper_id_cannot_break_the_query(store):
    assert _outstanding(store, paper_ids=["p0' OR '1'='1"]) == []


def test_candidates_count_the_whole_scope_not_just_what_is_left(store):
    store.save_extractions([_record("c0", status=SUCCEEDED)])

    assert store.count_candidates(chunker_id=CHUNKER) == 4
    assert store.count_candidates(chunker_id=CHUNKER, paper_ids=["p0"]) == 2


def test_chunk_text_comes_back_so_the_domain_need_not_re_read_it(store):
    [first] = store.outstanding_chunks(
        chunker_id=CHUNKER, model_id=MODEL, prompt_id=PROMPT, limit=1
    )

    assert first.text == "chunk 0"
    assert first.paper_id == "p0"
