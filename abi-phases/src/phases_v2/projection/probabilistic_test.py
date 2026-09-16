"""Backfill and filtered Effects search against the real dataset service."""

import csv
import io
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2.app.adapters.primary.SearchAPI import PREFIX, register
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.store import ensure_datasets
from phases_v2.projection.adapters.secondary.ProbabilisticContractValidator import (
    validate_relation,
)
from phases_v2.projection.factory import project_to_relations
from phases_v2.projection.probabilistic import project_relations
from phases_v2.search.adapters.secondary.DatasetExtractedItemsAdapter import (
    DatasetExtractedItemsAdapter,
)
from phases_v2.search.domain import SearchService
from phases_v2.search.fakes import FakeSemanticIndex

RELATION = dict(
    subject_process="spending less time alone than desired",
    subject_participant="person with unmet solitude preference",
    target_process="experiencing stress and depression",
    direction="increases",
    evidence_text=(
        "peer pairing may constitute a particularly effective intervention strategy "
        "for socially wary and anxious children because a sociable peer may serve "
        "as a role model, provide positive reinforcement, decrease anxiety, increase "
        "confidence, and enhance generalization"
    ),
)


@pytest.fixture
def corpus(tmp_path):
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path / 'catalog.sqlite'}",
            data_path=str(tmp_path / "data") + "/",
        )
    )
    ensure_datasets(dataset)
    rows = DatasetRowStore(dataset)
    rows.write_rows(
        "papers",
        [
            {
                "paper_id": "p",
                "file_name": "paper.pdf",
                "storage_prefix": "phases_v2/stress",
                "storage_key": "paper.pdf",
            }
        ],
    )
    rows.write_rows(
        "chunks",
        [{"chunk_id": "c", "paper_id": "p", "seq": 1, "text": "Exact source chunk"}],
    )
    rows.write_rows(
        "prompts",
        [
            {
                "prompt_id": "pr",
                "name": "probabilistic_processes",
                "output_key": "relations",
                "template": "Stored prompt",
            },
            {"prompt_id": "other", "output_key": "results"},
        ],
    )
    payloads = [
        str(RELATION),
        json.dumps(
            {**RELATION, "subject_process": "meditating", "direction": "decreases"}
        ),
        json.dumps({**RELATION, "direction": "no-effect"}),
        json.dumps(
            {
                **RELATION,
                "subject_process": "experiencing stress",
                "target_process": "sleeping",
            }
        ),
        json.dumps({**RELATION, "direction": "uncertain"}),
        json.dumps(
            {
                "relations": [
                    RELATION,
                    {
                        **RELATION,
                        "direction": "decreases",
                        "target_process": "inflammation",
                    },
                ]
            }
        ),
        json.dumps(RELATION),
        json.dumps(RELATION),
    ]
    rows.write_rows(
        "extractions",
        [
            {
                "extraction_id": f"e{i}",
                "model_id": "model",
                "status": "failed" if i == 7 else "succeeded",
            }
            for i in range(len(payloads))
        ],
    )
    rows.write_rows(
        "extracted_items",
        [
            {
                "item_id": f"i{i}",
                "extraction_id": f"e{i}",
                "chunk_id": "c",
                "paper_id": "p",
                "prompt_id": "other" if i == 6 else "pr",
                "text": text,
            }
            for i, text in enumerate(payloads)
        ],
    )
    return SimpleNamespace(services=SimpleNamespace(dataset=dataset)), rows


def test_backfill_is_bounded_repeatable_and_preserves_provenance(corpus):
    engine, rows = corpus
    dry = project_to_relations(engine, dry_run=True)
    assert (dry.examined, dry.projected, dry.invalid) == (6, 6, 1)
    assert rows.query("SELECT COUNT(*) AS n FROM probabilistic_relations")[0]["n"] == 0
    report = project_relations(
        rows.at_snapshot(rows.snapshot()), rows, validate_relation, batch_size=2
    )
    assert (report.examined, report.projected, report.invalid) == (6, 6, 1)
    assert "direction" in report.errors["i4"]
    relations = rows.query(
        "SELECT * FROM probabilistic_relations ORDER BY item_id, relation_index"
    )
    assert len(relations) == 6
    assert len({r["relation_id"] for r in relations}) == 6
    assert all(
        r["paper_id"] == "p" and r["chunk_id"] == "c" and r["model_id"] == "model"
        for r in relations
    )
    assert relations[0]["target_process"] == RELATION["target_process"]
    assert len(RELATION["evidence_text"]) > 200
    assert relations[0]["evidence_text"] == RELATION["evidence_text"]
    assert len(rows.query("SELECT * FROM extracted_items")) == 8
    rerun = project_to_relations(engine)
    assert (rerun.projected, rerun.invalid) == (0, 1)
    assert len(rows.query("SELECT * FROM probabilistic_relations")) == 6


def test_retry_after_ledger_failure_does_not_duplicate_relations(corpus):
    engine, rows = corpus

    class FailingLedger:
        def write_rows(self, name, values):
            if name == "projections":
                raise RuntimeError("ledger failure")
            rows.write_rows(name, values)

    with pytest.raises(RuntimeError, match="ledger failure"):
        project_relations(
            rows.at_snapshot(rows.snapshot()), FailingLedger(), validate_relation
        )
    assert project_to_relations(engine).projected == 6
    assert rows.query("SELECT COUNT(*) AS n FROM probabilistic_relations")[0]["n"] == 6


def test_effects_filters_target_fields_paginate_and_export(corpus):
    engine, rows = corpus
    project_to_relations(engine)
    app = FastAPI()
    register(
        app, SearchService(FakeSemanticIndex(), DatasetExtractedItemsAdapter(rows))
    )
    client = TestClient(app)
    params = dict(
        q="stress",
        direction="increases",
        limit=1,
        model="model",
        prompt="probabilistic_processes",
        path="phases_v2/stress",
    )
    first_response = client.get(f"{PREFIX}/effects", params=params)
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()
    assert first["total"] == 2
    assert first["hits"][0]["target_process"] == RELATION["target_process"]
    assert first["hits"][0]["chunk_text"] == "Exact source chunk"
    second = client.get(
        f"{PREFIX}/effects",
        params={
            **params,
            "offset": first["next_offset"],
            "snapshot": first["snapshot"],
        },
    ).json()
    assert second["total"] == 2 and not second["has_more"]
    assert second["hits"][0]["relation_id"] != first["hits"][0]["relation_id"]
    assert (
        client.get(
            f"{PREFIX}/effects",
            params=dict(q="stress", direction="decreases", subject="meditating"),
        ).json()["total"]
        == 1
    )
    assert (
        client.get(
            f"{PREFIX}/effects", params=dict(q="stress", direction="no-effect")
        ).json()["total"]
        == 1
    )
    assert (
        client.get(
            f"{PREFIX}/effects", params=dict(participant="unmet solitude")
        ).json()["total"]
        == 6
    )
    assert (
        client.get(
            f"{PREFIX}/effects", params=dict(q="stress", subject="stress")
        ).json()["total"]
        == 0
    )
    assert (
        client.get(f"{PREFIX}/effects", params=dict(direction="unknown")).status_code
        == 422
    )
    exported = client.get(f"{PREFIX}/export", params={**params, "mode": "effects"})
    assert exported.status_code == 200, exported.text
    data = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert len(data) == 2 and all(
        row["direction"] == "increases" and "stress" in row["target_process"]
        for row in data
    )
    assert client.get(f"{PREFIX}/effects").json()["total"] == 6


@pytest.mark.parametrize(
    "changes",
    [
        {"direction": "uncertain"},
        {"subject_participant": ""},
        {"evidence_text": ""},
    ],
)
def test_backfill_rows_execute_protovalidate_rules(changes):
    row = {
        **RELATION,
        **changes,
        "relation_id": "r",
        "item_id": "i",
        "extraction_id": "e",
        "chunk_id": "c",
        "paper_id": "p",
        "prompt_id": "pr",
        "model_id": "m",
        "relation_index": 0,
    }
    with pytest.raises(ValueError):
        validate_relation(row)


def test_relation_projection_preserves_selected_paper_scope(corpus):
    engine, rows = corpus
    assert project_to_relations(engine, paper_ids=[]).examined == 0
    assert project_to_relations(engine, paper_ids=["other"]).examined == 0
    assert rows.query("SELECT COUNT(*) AS n FROM probabilistic_relations")[0]["n"] == 0
    assert project_to_relations(engine, paper_ids=["p"]).projected == 6
