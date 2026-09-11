"""The adapter's SQL, against a real dataset seeded with the canonical fixture.

The domain tests use a fake whose behaviour is trivially correct; this checks
the joins that actually resolve provenance and answer keyword search.
"""

from __future__ import annotations

import pytest
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.store import ensure_datasets
from phases_v2.search.adapters.secondary.DatasetExtractedItemsAdapter import (
    DatasetExtractedItemsAdapter,
)
from phases_v2.search.contracts import assert_extracted_items_contract


@pytest.fixture
def adapter(tmp_path):
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path / 'catalog.sqlite'}",
            data_path=str(tmp_path / "warehouse") + "/",
        )
    )
    ensure_datasets(dataset)
    rows = DatasetRowStore(dataset)

    rows.write_rows(
        "papers",
        [
            {"paper_id": "paper-a", "file_name": "a.pdf"},
            {"paper_id": "paper-b", "file_name": "b.pdf"},
        ],
    )
    rows.write_rows(
        "prompts",
        [
            {
                "prompt_id": "prompt-effects-hash",
                "name": "solitude_effects",
                "output_key": "effects",
            },
            {
                "prompt_id": "prompt-causes-hash",
                "name": "solitude_causes",
                "output_key": "causes",
            },
        ],
    )
    rows.write_rows(
        "chunks",
        [
            {
                "chunk_id": "chunk-1",
                "paper_id": "paper-a",
                "chunker_id": "w1",
                "seq": 1,
                "text": "In several studies solitude reduces stress.",
            },
            {
                "chunk_id": "chunk-2",
                "paper_id": "paper-b",
                "chunker_id": "w1",
                "seq": 2,
                "text": "Prolonged isolation increases loneliness over time.",
            },
        ],
    )
    rows.write_rows(
        "extractions",
        [
            {
                "extraction_id": "extraction-1",
                "chunk_id": "chunk-1",
                "model_id": "openai/gpt-5-mini",
                "prompt_id": "prompt-effects-hash",
                "run_id": "r1",
                "status": "succeeded",
            },
            {
                "extraction_id": "extraction-2",
                "chunk_id": "chunk-2",
                "model_id": "openai/gpt-5-mini",
                "prompt_id": "prompt-causes-hash",
                "run_id": "r1",
                "status": "succeeded",
            },
        ],
    )
    rows.write_rows(
        "extracted_items",
        [
            {
                "item_id": "item-effects",
                "extraction_id": "extraction-1",
                "chunk_id": "chunk-1",
                "paper_id": "paper-a",
                "prompt_id": "prompt-effects-hash",
                "seq": 0,
                "text": "Solitude reduces stress.",
            },
            {
                "item_id": "item-causes",
                "extraction_id": "extraction-2",
                "chunk_id": "chunk-2",
                "paper_id": "paper-b",
                "prompt_id": "prompt-causes-hash",
                "seq": 0,
                "text": "Isolation increases loneliness.",
            },
        ],
    )
    return DatasetExtractedItemsAdapter(rows)


def test_the_contract(adapter):
    assert_extracted_items_contract(adapter)


def test_folders_and_stored_prompt_are_resolved_from_result_provenance(adapter):
    from phases_v2.sql import literal

    template = 'Original instructions, with "quotes".\nRead {chunk_text} exactly.'
    adapter._rows.query(
        "UPDATE papers SET storage_prefix = 'phases_v2/solitude', storage_key = 'paid/nested/a.pdf' WHERE paper_id = 'paper-a'"
    )
    adapter._rows.query(
        "UPDATE papers SET storage_prefix = 'phases_v2/solitude-other', storage_key = 'b.pdf' WHERE paper_id = 'paper-b'"
    )
    adapter._rows.query(
        f"UPDATE prompts SET template = {literal(template)} WHERE prompt_id = 'prompt-effects-hash'"
    )
    assert adapter.list_paths() == [
        "phases_v2",
        "phases_v2/solitude",
        "phases_v2/solitude-other",
        "phases_v2/solitude/paid",
        "phases_v2/solitude/paid/nested",
    ]
    assert adapter.paper_ids_for_paths(["phases_v2/solitude/"]) == ["paper-a"]
    assert adapter.paper_ids_for_paths(
        ["phases_v2/solitude", "phases_v2/solitude/paid"]
    ) == ["paper-a"]
    assert adapter.paper_ids_for_paths(
        ["phases_v2/solitude", "phases_v2/solitude-other"]
    ) == ["paper-a", "paper-b"]
    assert adapter.paper_ids_for_paths(["x' OR '1'='1"]) == []
    hits = adapter.keyword_search(["s"], None, 1, paths=["phases_v2/solitude-other"])
    assert [hit[0] for hit in hits] == ["item-causes"]
    location = adapter.resolve_locations(["item-effects"])["item-effects"]
    assert location.source_path == "phases_v2/solitude/paid/nested"
    assert location.prompt_template == template
    assert adapter.keyword_search(["solitude"], None, 10, paths=["unknown"]) == []


def test_model_facets_and_keyword_filters_use_extraction_provenance(adapter):
    adapter._rows.query(
        "UPDATE extractions SET model_id = 'openrouter/claude-sonnet-4.6' "
        "WHERE extraction_id = 'extraction-2'"
    )
    assert adapter.list_models() == [
        "openai/gpt-5-mini",
        "openrouter/claude-sonnet-4.6",
    ]
    assert (
        adapter.keyword_search(
            ["solitude"], None, 1, models=["openrouter/claude-sonnet-4.6"]
        )
        == []
    )
    hits = adapter.keyword_search(
        ["s"], None, 1, models=["openrouter/claude-sonnet-4.6"]
    )
    assert [hit[0] for hit in hits] == ["item-causes"]
    assert (
        adapter.keyword_search(
            ["isolation"],
            ["solitude_effects"],
            1,
            models=["openrouter/claude-sonnet-4.6"],
        )
        == []
    )
    assert (
        adapter.keyword_search(["isolation"], None, 10, models=["x' OR '1'='1"]) == []
    )


def test_a_hostile_item_id_cannot_break_resolve_locations(adapter):
    assert adapter.resolve_locations(["x' OR '1'='1"]) == {}


def test_a_hostile_token_cannot_break_keyword_search(adapter):
    assert adapter.keyword_search(["x' OR '1'='1"], prompts=None, limit=10) == []


def test_a_hostile_prompt_facet_cannot_break_keyword_search(adapter):
    hits = adapter.keyword_search(["solitude"], prompts=["x' OR '1'='1"], limit=10)
    assert hits == []


def test_an_empty_item_id_list_is_a_no_op(adapter):
    assert adapter.resolve_locations([]) == {}


def test_count_and_pagination_use_identical_filters_and_stable_ties(adapter):
    adapter._rows.write_rows(
        "extracted_items",
        [
            {
                "item_id": f"bulk-{i:04d}",
                "text": "bulkneedle evidence",
                "extraction_id": "extraction-1",
                "chunk_id": "chunk-1",
                "paper_id": "paper-a",
                "prompt_id": "prompt-effects-hash",
                "seq": i,
            }
            for i in range(275)
        ],
    )
    assert (
        adapter.keyword_count(
            ["bulkneedle"], ["solitude_effects"], ["openai/gpt-5-mini"]
        )
        == 275
    )
    assert adapter.keyword_count(["bulkneedle"], ["solitude_causes"]) == 0
    ids = []
    for offset in (0, 100, 200):
        ids.extend(
            row[0]
            for row in adapter.keyword_search(
                ["bulkneedle"],
                ["solitude_effects"],
                100,
                models=["openai/gpt-5-mini"],
                offset=offset,
            )
        )
    assert ids == [f"bulk-{i:04d}" for i in range(275)]
    assert adapter.keyword_count([]) == 0


def test_read_view_pins_keyword_count_and_pages_while_new_items_arrive(adapter):
    view = adapter.at_snapshot(adapter.snapshot())
    before = view.keyword_count(["solitude"])
    adapter._rows.write_rows(
        "extracted_items",
        [{"item_id": "later", "text": "solitude", "paper_id": "paper-a"}],
    )
    assert adapter.keyword_count(["solitude"]) == before + 1
    assert view.keyword_count(["solitude"]) == before
    assert len(view.keyword_search(["solitude"], None, 100)) == before
