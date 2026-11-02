"""The rename migration, against a real local dataset catalog and Qdrant."""

import json
from datetime import UTC, datetime

import pytest
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService
from qdrant_client import QdrantClient
from qdrant_client import models as qm

from phases_v2 import identity
from phases_v2.datasets import store
from phases_v2.datasets.schemas import NAMESPACE
from phases_v2.migrations.rename_prompt import (
    ITEMS_COLLECTION,
    NEW_NAME,
    OLD_NAME,
    MigrationError,
    QdrantVectorPoints,
    migrate,
)
from phases_v2.projection.interfaces import GRAPH, VECTOR_ITEMS
from phases_v2.prompts.domain import PromptTemplate
from phases_v2.prompts.templates import declared_prompts

OLD_TEMPLATE = (
    "You are extracting LOGICAL SENTENCES from:\n{chunk_text}\n"
    'Return {"logical_sentences": ["If ..., then ..."]}'
)
OTHER = PromptTemplate(
    name="solitude_what", template="Find {chunk_text}", output_key="what"
)
CURRENT = PromptTemplate(
    name=NEW_NAME,
    template='CONDITIONAL STATEMENTS from {chunk_text}: {"conditional_statement": []}',
    output_key="conditional_statement",
)
OLD_ID = identity.prompt_id(OLD_NAME, OLD_TEMPLATE)
NEW_ID = identity.prompt_id(NEW_NAME, OLD_TEMPLATE)
GPT = "openai/gpt-4.1-mini"
CLAUDE = "anthropic/claude-sonnet-4.6"
WHEN = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


_TABLES = (
    "prompts",
    "extractions",
    "extracted_items",
    "extraction_runs",
    "probabilistic_relations",
    "projections",
    "pipelines",
    "run_requests",
)


@pytest.fixture(scope="module")
def catalog(tmp_path_factory) -> DatasetService:
    # Creating the datasets is the slow part of every test, so one catalog is
    # shared and emptied between tests.
    root = tmp_path_factory.mktemp("rename")
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


@pytest.fixture
def qdrant() -> QdrantClient:
    client = QdrantClient(":memory:")
    client.create_collection(
        ITEMS_COLLECTION,
        vectors_config=qm.VectorParams(size=2, distance=qm.Distance.COSINE),
    )
    return client


def _prompt_row(prompt: PromptTemplate, name=None) -> dict:
    return {
        "prompt_id": prompt.prompt_id,
        "name": name or prompt.name,
        "prompt_sha256": identity.prompt_sha256(prompt.template),
        "template": prompt.template,
        "output_key": prompt.output_key,
        "registered_at": WHEN,
    }


def _extraction(*, chunk, model, prompt_id, texts, status="succeeded", run="run-1"):
    """The rows one extraction leaves: ``(extraction row, item rows)``."""
    extraction = identity.extraction_id(chunk, model, prompt_id)
    ok = status == "succeeded"
    return (
        {
            "extraction_id": extraction,
            "chunk_id": chunk,
            "model_id": model,
            "prompt_id": prompt_id,
            "run_id": run,
            "status": status,
            "response": {OLD_NAME: texts} if ok else None,
            "raw_response": json.dumps({OLD_NAME: texts}) if ok else "garbage",
            "error": None if ok else "invalid ConditionalStatementOutput",
            "item_count": len(texts) if ok else 0,
            "completed_at": WHEN,
        },
        [
            {
                "item_id": identity.item_id(extraction, seq),
                "extraction_id": extraction,
                "chunk_id": chunk,
                "paper_id": f"paper-{chunk}",
                "prompt_id": prompt_id,
                "seq": seq,
                "text": text,
            }
            for seq, text in enumerate(texts)
        ],
    )


def _seed_extractions(dataset, *extractions):
    store.write_rows(dataset, "extractions", [row for row, _ in extractions])
    items = [item for _, rows in extractions for item in rows]
    if items:
        store.write_rows(dataset, "extracted_items", items)
    return [row["extraction_id"] for row, _ in extractions]


def _seed_point(qdrant, item_id, prompt_id, prompt_name, vector=(1.0, 0.0)):
    qdrant.upsert(
        ITEMS_COLLECTION,
        [
            qm.PointStruct(
                id=abs(hash(item_id)) % (2**31),
                vector=list(vector),
                payload={
                    "item_id": item_id,
                    "prompt_id": prompt_id,
                    "prompt_name": prompt_name,
                },
            )
        ],
    )


@pytest.fixture
def seeded(dataset, qdrant):
    """Two chunks on gpt-4.1-mini and one on claude (one of them a failure),
    one chunk that also has a succeeded extraction under the current
    conditional_statement text, and an unrelated prompt that must not move."""
    store.write_rows(
        dataset,
        "prompts",
        [
            _prompt_row(PromptTemplate(OLD_NAME, OLD_TEMPLATE, OLD_NAME)),
            _prompt_row(CURRENT),
            _prompt_row(OTHER),
        ],
    )
    names = ("c1-gpt", "c2-gpt", "c1-claude", "c3-claude-failed")
    old = dict(
        zip(
            names,
            _seed_extractions(
                dataset,
                _extraction(
                    chunk="c1",
                    model=GPT,
                    prompt_id=OLD_ID,
                    texts=["If a, then b.", "If c, then d."],
                ),
                _extraction(
                    chunk="c2", model=GPT, prompt_id=OLD_ID, texts=["If e, then f."]
                ),
                _extraction(
                    chunk="c1",
                    model=CLAUDE,
                    prompt_id=OLD_ID,
                    texts=["If g, then h."],
                    run="run-2",
                ),
                _extraction(
                    chunk="c3",
                    model=CLAUDE,
                    prompt_id=OLD_ID,
                    texts=[],
                    status="failed",
                    run="run-2",
                ),
            ),
        )
    )
    # A chunk that already has current-text results: both must survive.
    current, other = _seed_extractions(
        dataset,
        _extraction(
            chunk="c1", model=GPT, prompt_id=CURRENT.prompt_id, texts=["If x, then y."]
        ),
        _extraction(chunk="c1", model=GPT, prompt_id=OTHER.prompt_id, texts=["what"]),
    )
    store.write_rows(
        dataset,
        "extraction_runs",
        [
            {
                "run_id": run,
                "chunker_id": "chunker",
                "model_id": model,
                "prompt_id": OTHER.prompt_id if run == "run-3" else OLD_ID,
                "started_at": WHEN,
                "finished_at": WHEN,
                "succeeded": 3,
                "failed": 1,
                "skipped": 0,
            }
            for run, model in (("run-1", GPT), ("run-2", CLAUDE), ("run-3", GPT))
        ],
    )
    store.write_rows(
        dataset,
        "pipelines",
        [
            {
                "pipeline_id": "pipe-1",
                "name": "Saved",
                "inputs": {
                    "locations": ["phases_v2/a"],
                    "chunker_id": "chunker",
                    "prompt_ids": [OTHER.prompt_id, OLD_ID],
                    "model_id": GPT,
                },
                "created_at": WHEN,
            },
            {
                "pipeline_id": "pipe-2",
                "name": "Untouched",
                "inputs": {"prompt_ids": [OTHER.prompt_id]},
                "created_at": WHEN,
            },
        ],
    )
    store.write_rows(
        dataset,
        "run_requests",
        [
            {
                "request_id": "req-1",
                "status": "succeeded",
                "locations": ["phases_v2/a"],
                "chunker_id": "chunker",
                "prompt_ids": [OLD_ID, OTHER.prompt_id],
                "model_id": GPT,
                "requested_at": WHEN,
            },
            {
                "request_id": "req-2",
                "status": "succeeded",
                "locations": ["phases_v2/a"],
                "chunker_id": "chunker",
                "prompt_ids": [OTHER.prompt_id],
                "model_id": GPT,
                "requested_at": WHEN,
            },
        ],
    )

    old_items = [
        row["item_id"]
        for row in dataset.query(
            f"SELECT item_id FROM extracted_items WHERE prompt_id = '{OLD_ID}'",
            namespace=NAMESPACE,
        ).rows
    ]
    other_items = [
        row["item_id"]
        for row in dataset.query(
            f"SELECT item_id FROM extracted_items WHERE prompt_id = '{OTHER.prompt_id}'",
            namespace=NAMESPACE,
        ).rows
    ]
    store.write_rows(
        dataset,
        "projections",
        [
            {"target": VECTOR_ITEMS, "key": key, "projected_at": WHEN}
            for key in old_items + other_items
        ]
        + [{"target": "vector_chunks", "key": "c1", "projected_at": WHEN}],
    )
    for key in old_items:
        _seed_point(qdrant, key, OLD_ID, OLD_NAME)
    for key in other_items:
        _seed_point(qdrant, key, OTHER.prompt_id, "solitude_what")
    return {"old": old, "current": current, "other": other, "old_items": old_items}


def _ids(dataset, sql):
    return sorted(
        next(iter(row.values())) for row in dataset.query(sql, namespace=NAMESPACE).rows
    )


def _run(dataset, qdrant, **kwargs):
    return migrate(dataset, QdrantVectorPoints(qdrant), **kwargs)


def _points(qdrant, **match):
    return qdrant.count(
        ITEMS_COLLECTION,
        count_filter=qm.Filter(
            must=[
                qm.FieldCondition(key=k, match=qm.MatchValue(value=v))
                for k, v in match.items()
            ]
        ),
        exact=True,
    ).count


# -- success ------------------------------------------------------------


def test_the_new_prompt_carries_the_stored_text_and_the_old_prompt_is_gone(
    dataset, qdrant, seeded
):
    _run(dataset, qdrant)

    prompts = dataset.query(
        "SELECT prompt_id, name, template, output_key, prompt_sha256 FROM prompts "
        f"WHERE prompt_id = '{NEW_ID}'",
        namespace=NAMESPACE,
    ).rows
    assert prompts == [
        {
            "prompt_id": NEW_ID,
            "name": NEW_NAME,
            "template": OLD_TEMPLATE,
            "output_key": NEW_NAME,
            "prompt_sha256": identity.prompt_sha256(OLD_TEMPLATE),
        }
    ]
    assert (
        _ids(dataset, f"SELECT prompt_id FROM prompts WHERE name = '{OLD_NAME}'") == []
    )
    assert NEW_ID.startswith(f"{NEW_NAME}_")


def test_extractions_are_rekeyed_by_identity_and_keep_their_responses(
    dataset, qdrant, seeded
):
    _run(dataset, qdrant)

    rows = {
        row["chunk_id"] + "/" + row["model_id"]: row
        for row in dataset.query(
            f"SELECT * FROM extractions WHERE prompt_id = '{NEW_ID}'",
            namespace=NAMESPACE,
        ).rows
    }
    assert sorted(rows) == [f"c1/{CLAUDE}", f"c1/{GPT}", f"c2/{GPT}", f"c3/{CLAUDE}"]
    first = rows[f"c1/{GPT}"]
    assert first["extraction_id"] == identity.extraction_id("c1", GPT, NEW_ID)
    assert first["response"] == {OLD_NAME: ["If a, then b.", "If c, then d."]}
    assert first["raw_response"] == json.dumps(
        {OLD_NAME: ["If a, then b.", "If c, then d."]}
    )
    assert first["run_id"] == "run-1"
    failed = rows[f"c3/{CLAUDE}"]
    assert failed["status"] == "failed"
    assert failed["error"] == "invalid ConditionalStatementOutput"
    assert failed["raw_response"] == "garbage"
    assert _ids(
        dataset, f"SELECT count(*) FROM extractions WHERE prompt_id = '{OLD_ID}'"
    ) == [0]


def test_items_are_rekeyed_from_their_new_extraction_with_text_and_order_kept(
    dataset, qdrant, seeded
):
    _run(dataset, qdrant)

    items = dataset.query(
        f"SELECT * FROM extracted_items WHERE prompt_id = '{NEW_ID}'",
        namespace=NAMESPACE,
    ).rows
    assert {(i["chunk_id"], i["seq"], i["text"]) for i in items} == {
        ("c1", 0, "If a, then b."),
        ("c1", 1, "If c, then d."),
        ("c1", 0, "If g, then h."),
        ("c2", 0, "If e, then f."),
    }
    assert len(items) == 4
    for item in items:
        extraction = identity.extraction_id(
            item["chunk_id"],
            CLAUDE if item["text"] == "If g, then h." else GPT,
            NEW_ID,
        )
        assert item["extraction_id"] == extraction
        assert item["item_id"] == identity.item_id(extraction, item["seq"])
        assert item["paper_id"] == f"paper-{item['chunk_id']}"
    assert _ids(
        dataset, f"SELECT count(*) FROM extracted_items WHERE prompt_id = '{OLD_ID}'"
    ) == [0]


def test_a_chunk_with_both_versions_keeps_both(dataset, qdrant, seeded):
    _run(dataset, qdrant)

    rows = dataset.query(
        "SELECT prompt_id, status FROM extractions "
        f"WHERE chunk_id = 'c1' AND model_id = '{GPT}' ORDER BY prompt_id",
        namespace=NAMESPACE,
    ).rows
    prompts = {row["prompt_id"] for row in rows}
    assert {CURRENT.prompt_id, NEW_ID, OTHER.prompt_id} == prompts
    assert CURRENT.prompt_id != NEW_ID
    assert all(row["status"] == "succeeded" for row in rows)


def test_unrelated_rows_are_not_touched(dataset, qdrant, seeded):
    before = _ids(
        dataset,
        f"SELECT extraction_id FROM extractions WHERE prompt_id = '{OTHER.prompt_id}'",
    )

    _run(dataset, qdrant)

    assert before == _ids(
        dataset,
        f"SELECT extraction_id FROM extractions WHERE prompt_id = '{OTHER.prompt_id}'",
    )
    assert _ids(dataset, "SELECT count(*) FROM prompts") == [3]
    assert _points(qdrant, prompt_name="solitude_what") == 1


def test_runs_pipelines_and_requests_are_pointed_at_the_new_prompt(
    dataset, qdrant, seeded
):
    _run(dataset, qdrant)

    runs = {
        row["run_id"]: row["prompt_id"]
        for row in dataset.query(
            "SELECT run_id, prompt_id FROM extraction_runs", namespace=NAMESPACE
        ).rows
    }
    assert runs == {"run-1": NEW_ID, "run-2": NEW_ID, "run-3": OTHER.prompt_id}
    pipelines = {
        row["pipeline_id"]: row["inputs"]
        for row in dataset.query(
            "SELECT pipeline_id, inputs FROM pipelines", namespace=NAMESPACE
        ).rows
    }
    assert pipelines["pipe-1"]["prompt_ids"] == [OTHER.prompt_id, NEW_ID]
    assert pipelines["pipe-1"]["locations"] == ["phases_v2/a"]
    assert pipelines["pipe-2"]["prompt_ids"] == [OTHER.prompt_id]
    requests = {
        row["request_id"]: row["prompt_ids"]
        for row in dataset.query(
            "SELECT request_id, prompt_ids FROM run_requests", namespace=NAMESPACE
        ).rows
    }
    assert requests == {"req-1": [NEW_ID, OTHER.prompt_id], "req-2": [OTHER.prompt_id]}


def test_old_vector_points_and_ledger_entries_are_deleted_so_they_project_again(
    dataset, qdrant, seeded
):
    old_items = set(seeded["old_items"])
    ledger_before = set(_ids(dataset, "SELECT key FROM projections"))
    assert old_items <= ledger_before

    _run(dataset, qdrant)

    ledger_after = set(_ids(dataset, "SELECT key FROM projections"))
    assert ledger_after == ledger_before - old_items
    assert "c1" in ledger_after
    assert _points(qdrant, prompt_name=OLD_NAME) == 0
    assert _points(qdrant, prompt_id=OLD_ID) == 0
    assert _points(qdrant, prompt_name="solitude_what") == 1
    # Nothing is projected under the new ids yet: the vector projection does it.
    assert _points(qdrant, prompt_id=NEW_ID) == 0
    new_items = set(
        _ids(
            dataset, f"SELECT item_id FROM extracted_items WHERE prompt_id = '{NEW_ID}'"
        )
    )
    assert not new_items & ledger_after


def test_the_report_counts_before_and_after(dataset, qdrant, seeded):
    report = _run(dataset, qdrant)

    assert report.before["prompts named logical_sentences"] == 1
    assert report.before["extractions, old prompt id"] == 4
    assert report.before["extracted_items, old prompt id"] == 4
    assert report.before["extraction_runs, old prompt id"] == 2
    assert report.before["projections ledger, old item/extraction ids"] == 4
    assert report.before["pipelines naming the old prompt"] == 1
    assert report.before["run_requests naming the old prompt"] == 1
    assert report.before["qdrant points, old prompt"] == 4
    assert report.before["extractions, new prompt id"] == 0
    assert report.after["prompts named logical_sentences"] == 0
    assert report.after["extractions, old prompt id"] == 0
    assert report.after["extractions, new prompt id"] == 4
    assert report.after["extracted_items, new prompt id"] == 4
    assert report.after["extraction_runs, new prompt id"] == 2
    assert report.after["qdrant points, old prompt"] == 0
    assert "before" in report.render()
    assert "extractions, new prompt id" in report.render()


# -- dry run and re-run -------------------------------------------------


def _snapshot(dataset, qdrant):
    tables = (
        "prompts",
        "extractions",
        "extracted_items",
        "extraction_runs",
        "pipelines",
        "run_requests",
        "projections",
    )
    return (
        {t: _ids(dataset, f"SELECT count(*) FROM {t}") for t in tables},
        {
            t: sorted(
                map(
                    json.dumps,
                    dataset.query(f"SELECT * FROM {t}", namespace=NAMESPACE).rows,
                )
            )
            for t in tables
        },
        qdrant.count(ITEMS_COLLECTION, exact=True).count,
    )


def test_a_dry_run_changes_nothing_and_predicts_the_real_run(dataset, qdrant, seeded):
    before = _snapshot(dataset, qdrant)

    dry = _run(dataset, qdrant, dry_run=True)

    assert _snapshot(dataset, qdrant) == before
    assert dry.dry_run is True
    assert "dry run" in dry.render()
    real = _run(dataset, qdrant)
    assert dry.before == real.before
    assert dry.after == real.after


def test_running_again_does_nothing(dataset, qdrant, seeded):
    _run(dataset, qdrant)
    finished = _snapshot(dataset, qdrant)

    again = _run(dataset, qdrant)

    assert _snapshot(dataset, qdrant) == finished
    assert all(count == 0 for count in again.before.values())
    assert again.before == again.after


def test_a_run_that_stopped_before_deleting_resumes(
    dataset, qdrant, seeded, monkeypatch
):
    from phases_v2.migrations import rename_prompt

    def stop(*args, **kwargs):
        raise RuntimeError("connection lost")

    monkeypatch.setattr(rename_prompt, "_drop_old", stop)
    with pytest.raises(RuntimeError):
        _run(dataset, qdrant)
    # Re-keyed rows exist beside the old ones; nothing has been deleted.
    assert _ids(
        dataset, f"SELECT count(*) FROM extractions WHERE prompt_id = '{NEW_ID}'"
    ) == [4]
    assert _ids(
        dataset, f"SELECT count(*) FROM extractions WHERE prompt_id = '{OLD_ID}'"
    ) == [4]
    monkeypatch.undo()

    _run(dataset, qdrant)

    assert _ids(
        dataset, f"SELECT count(*) FROM extractions WHERE prompt_id = '{NEW_ID}'"
    ) == [4]
    assert _ids(
        dataset, f"SELECT count(*) FROM extractions WHERE prompt_id = '{OLD_ID}'"
    ) == [0]
    assert _ids(dataset, f"SELECT count(*) FROM prompts WHERE name = '{OLD_NAME}'") == [
        0
    ]
    assert _points(qdrant, prompt_name=OLD_NAME) == 0


def test_a_succeeded_result_already_under_the_new_id_is_not_overwritten(
    dataset, qdrant, seeded
):
    (kept,) = _seed_extractions(
        dataset,
        _extraction(
            chunk="c2",
            model=GPT,
            prompt_id=NEW_ID,
            texts=["If rerun, then newer."],
        ),
    )

    _run(dataset, qdrant)

    row = dataset.query(
        f"SELECT response FROM extractions WHERE extraction_id = '{kept}'",
        namespace=NAMESPACE,
    ).rows[0]
    assert row["response"] == {OLD_NAME: ["If rerun, then newer."]}
    assert _ids(
        dataset,
        f"SELECT text FROM extracted_items WHERE chunk_id = 'c2' AND prompt_id = '{NEW_ID}'",
    ) == ["If rerun, then newer."]


# -- refusals -----------------------------------------------------------


def test_extractions_already_in_the_graph_stop_the_migration_untouched(
    dataset, qdrant, seeded
):
    store.write_rows(
        dataset,
        "projections",
        [{"target": GRAPH, "key": seeded["old"]["c1-gpt"], "projected_at": WHEN}],
    )
    before = _snapshot(dataset, qdrant)

    with pytest.raises(MigrationError, match="graph"):
        _run(dataset, qdrant)

    assert _snapshot(dataset, qdrant) == before


def test_an_item_without_its_extraction_stops_the_migration_untouched(
    dataset, qdrant, seeded
):
    store.delete_rows(
        dataset, "extractions", "extraction_id", [seeded["old"]["c2-gpt"]]
    )
    before = _snapshot(dataset, qdrant)

    with pytest.raises(MigrationError, match="no row"):
        _run(dataset, qdrant)

    assert _snapshot(dataset, qdrant) == before


def test_the_migrated_prompt_is_the_one_the_code_declares(dataset, qdrant):
    # The stored text, taken from the declared version of it, gives the id the
    # engine registers on start; the two must agree or the prompt would exist
    # twice.
    declared = next(
        t for t in declared_prompts() if t.prompt_id.endswith("1624d6b1d2f8")
    )
    store.write_rows(
        dataset,
        "prompts",
        [
            _prompt_row(
                PromptTemplate(OLD_NAME, declared.template, OLD_NAME),
            )
        ],
    )

    _run(dataset, qdrant)

    rows = dataset.query(
        "SELECT prompt_id, name, template, output_key FROM prompts",
        namespace=NAMESPACE,
    ).rows
    assert rows == [
        {
            "prompt_id": declared.prompt_id,
            "name": declared.name,
            "template": declared.template,
            "output_key": declared.output_key,
        }
    ]


def test_nothing_in_the_declared_catalog_is_named_after_the_old_prompt():
    assert OLD_NAME not in {template.name for template in declared_prompts()}
