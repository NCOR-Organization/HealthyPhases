"""Papers, chunks, prompt tries and version history over real datasets.

The try endpoint runs against a DuckLake store wrapped to record writes, with a
fake model, so these tests show both that the SQL reads what the pipeline wrote
and that trying leaves every dataset exactly as it was.
"""

import json
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from phases_v2 import identity
from phases_v2.app.adapters.primary.PipelineAPI import PREFIX, register
from phases_v2.app.service import PipelineAppService
from phases_v2.chunking.chunkers import WINDOW_512_128
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.schemas import DATASETS
from phases_v2.datasets.store import ensure_datasets
from phases_v2.extraction.fakes import FakeModel
from phases_v2.prompts.domain import PromptTemplate
from phases_v2.requests.adapters.secondary.DatasetRequestStore import (
    DatasetRequestStore,
)

MODEL = "openai/gpt-4.1-mini"
OTHER_MODEL = "openai/gpt-5-mini"
CHUNKER = WINDOW_512_128.chunker_id
OLD = PromptTemplate("Claims", "Old {chunk_text}", "results")
NEW = PromptTemplate("Claims", "New {chunk_text}", "results")
# Stamped by a restart in September, but already run in January.
RESTARTED = PromptTemplate("Effects", "Built in {chunk_text}", "effects")
LATER = PromptTemplate("Effects", "Saved in May {chunk_text}", "effects")
LONG_TEXT = "word " * 100


class RecordingRows:
    """The real row store, with every write noted."""

    def __init__(self, inner):
        self._inner = inner
        self.writes: list[str] = []

    def write_rows(self, name, rows):
        self.writes.append(name)
        self._inner.write_rows(name, rows)

    def query(self, sql):
        return self._inner.query(sql)

    def snapshot(self):
        return self._inner.snapshot()

    def at_snapshot(self, snapshot):
        return self._inner.at_snapshot(snapshot)


def _chunk(paper, chunker, seq):
    return identity.chunk_id(paper, chunker, seq)


def _seed(rows):
    def at(month):
        return datetime(2026, month, 1, tzinfo=UTC)

    rows.write_rows(
        "papers",
        [
            {
                "paper_id": "p1",
                "file_name": "Loneliness and sleep.pdf",
                "storage_prefix": "phases_v2/gero",
                "storage_key": "studies/loneliness.pdf",
                "text_key": "t1",
            },
            {"paper_id": "p2", "file_name": "Gero%study.pdf", "text_key": "t2"},
            {"paper_id": "p3", "file_name": "Not rendered.pdf", "text_key": None},
        ],
    )
    rows.write_rows(
        "chunks",
        [
            {
                "chunk_id": _chunk("p1", CHUNKER, seq),
                "paper_id": "p1",
                "chunker_id": CHUNKER,
                "seq": seq,
                "text": LONG_TEXT if seq == 3 else f"Paper one chunk {seq}",
            }
            for seq in range(4)
        ]
        + [
            {
                "chunk_id": _chunk("p2", "window_1_aaa", seq),
                "paper_id": "p2",
                "chunker_id": "window_1_aaa",
                "seq": seq,
                "text": f"Paper two chunk {seq}",
            }
            for seq in range(2)
        ],
    )
    rows.write_rows(
        "prompts",
        [
            {
                "prompt_id": p.prompt_id,
                "name": p.name,
                "prompt_sha256": identity.prompt_sha256(p.template),
                "template": p.template,
                "output_key": p.output_key,
                "registered_at": at(month),
            }
            for p, month in ((OLD, 1), (NEW, 2))
        ],
    )

    def extraction(seq, model, status, count):
        return {
            "extraction_id": identity.extraction_id(
                _chunk("p1", CHUNKER, seq), model, OLD.prompt_id
            ),
            "chunk_id": _chunk("p1", CHUNKER, seq),
            "model_id": model,
            "prompt_id": OLD.prompt_id,
            "run_id": f"req-1:{OLD.prompt_id}",
            "status": status,
            "error": "rate limited" if status == "failed" else None,
            "item_count": count,
        }

    rows.write_rows(
        "extractions",
        [
            extraction(0, MODEL, "succeeded", 2),
            extraction(1, MODEL, "failed", 0),
            extraction(0, OTHER_MODEL, "succeeded", 1),
        ],
    )
    stored = identity.extraction_id(_chunk("p1", CHUNKER, 0), MODEL, OLD.prompt_id)
    elsewhere = identity.extraction_id(
        _chunk("p1", CHUNKER, 0), OTHER_MODEL, OLD.prompt_id
    )
    rows.write_rows(
        "extracted_items",
        [
            {
                "item_id": identity.item_id(extraction_id, seq),
                "extraction_id": extraction_id,
                "chunk_id": _chunk("p1", CHUNKER, 0),
                "paper_id": "p1",
                "prompt_id": OLD.prompt_id,
                "seq": seq,
                "text": text,
            }
            for extraction_id, seq, text in (
                (stored, 0, "old claim one"),
                (stored, 1, "old claim two"),
                (elsewhere, 0, "other model claim"),
            )
        ],
    )
    rows.write_rows(
        "prompts",
        [
            {
                "prompt_id": p.prompt_id,
                "name": p.name,
                "prompt_sha256": identity.prompt_sha256(p.template),
                "template": p.template,
                "output_key": p.output_key,
                "registered_at": at(month),
            }
            for p, month in ((RESTARTED, 9), (LATER, 5))
        ],
    )
    rows.write_rows(
        "extraction_runs",
        [
            {
                "run_id": f"req-0:{RESTARTED.prompt_id}",
                "chunker_id": CHUNKER,
                "model_id": MODEL,
                "prompt_id": RESTARTED.prompt_id,
                "started_at": at(1),
                "finished_at": at(1),
                "succeeded": 1,
                "failed": 0,
                "skipped": 0,
            },
            {
                "run_id": f"req-1:{OLD.prompt_id}",
                "chunker_id": CHUNKER,
                "model_id": MODEL,
                "prompt_id": OLD.prompt_id,
                "started_at": at(3),
                "finished_at": at(3),
                "succeeded": 1,
                "failed": 1,
                "skipped": 0,
            },
        ],
    )
    rows.write_rows(
        "run_requests",
        [
            {
                "request_id": "req-1",
                "status": "succeeded",
                "locations": ["phases_v2"],
                "chunker_id": CHUNKER,
                "prompt_ids": [OLD.prompt_id, "something-else"],
                "model_id": MODEL,
                "requested_by": "member@example.org",
                "requested_at": at(3),
            }
        ],
    )


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    path = tmp_path_factory.mktemp("playground")
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{path / 'catalog.sqlite'}",
            data_path=str(path / "warehouse") + "/",
        )
    )
    ensure_datasets(dataset)
    _seed(DatasetRowStore(dataset))
    return dataset


@pytest.fixture
def env(dataset, monkeypatch):
    monkeypatch.setenv("ABI_API_KEY", "test-pipeline-key")
    rows = RecordingRows(DatasetRowStore(dataset))
    model = {"current": FakeModel(json.dumps({"results": ["a new claim"]}))}
    service = PipelineAppService(
        DatasetRequestStore(rows),
        rows=rows,
        model_factory=lambda model_id, output_key: model["current"],
    )
    app = FastAPI()
    register(app, service)
    client = TestClient(app, headers={"Authorization": "Bearer test-pipeline-key"})
    yield client, rows, model
    client.close()


def _counts(rows):
    return {
        spec.name: rows.query(f"SELECT count(*) AS n FROM {spec.name}")[0]["n"]  # nosec B608
        for spec in DATASETS
    }


def _try_body(**change):
    body = {
        "draft": {
            "name": "Claims",
            "template": "Draft {chunk_text}",
            "output_key": "results",
        },
        "model_id": MODEL,
        "paper_id": "p1",
        "chunker_id": CHUNKER,
        "seqs": [0, 1, 2],
        "baseline_prompt_id": OLD.prompt_id,
    }
    body.update(change)
    return {key: value for key, value in body.items() if value is not None}


# -- papers and chunks -----------------------------------------------------------


def test_papers_lists_only_ingested_papers_by_file_name_with_chunk_counts(env):
    client, _, _ = env

    page = client.get(f"{PREFIX}/papers").json()

    assert page["total"] == 2
    assert [p["file_name"] for p in page["papers"]] == [
        "Gero%study.pdf",
        "Loneliness and sleep.pdf",
    ]
    assert page["papers"][1]["chunks"] == {CHUNKER: 4}
    assert page["papers"][1]["path"] == "phases_v2/gero/studies/loneliness.pdf"
    assert page["papers"][0]["path"] is None
    assert page["papers"][0]["chunks"] == {"window_1_aaa": 2}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("q=SLEEP", ["p1"]),
        # The path counts too, so a folder name finds its papers.
        ("q=gero/studies", ["p1"]),
        # A search for % means the character, not "anything".
        ("q=%25", ["p2"]),
        (f"chunker_id={CHUNKER}", ["p1"]),
        ("limit=1&offset=1", ["p1"]),
        ("q=nothing-like-this", []),
    ],
)
def test_papers_can_be_searched_filtered_by_chunker_and_paged(env, query, expected):
    client, _, _ = env

    page = client.get(f"{PREFIX}/papers?{query}").json()

    assert [p["paper_id"] for p in page["papers"]] == expected


def test_a_papers_chunks_come_in_order_with_short_previews(env):
    client, _, _ = env

    body = client.get(f"{PREFIX}/papers/p1/chunks?chunker_id={CHUNKER}").json()

    assert [c["seq"] for c in body["chunks"]] == [0, 1, 2, 3]
    assert body["chunks"][0]["preview"] == "Paper one chunk 0"
    assert body["chunks"][3]["preview"].endswith("…")
    assert len(body["chunks"][3]["preview"]) <= 161
    assert body["chunked_with"] == [CHUNKER]


def test_chunks_of_a_paper_cut_with_another_chunker_are_empty_and_say_so(env):
    client, _, _ = env

    body = client.get(f"{PREFIX}/papers/p2/chunks?chunker_id={CHUNKER}").json()

    assert body["chunks"] == []
    assert body["chunked_with"] == ["window_1_aaa"]


def test_chunks_of_an_unknown_paper_are_not_found(env):
    client, _, _ = env

    response = client.get(f"{PREFIX}/papers/p3/chunks?chunker_id={CHUNKER}")

    assert response.status_code == 404
    assert response.json()["detail"] == "That paper has not been ingested."


# -- trying ------------------------------------------------------------------------


def test_a_try_returns_items_per_chunk_beside_the_baseline_and_writes_nothing(env):
    client, rows, model = env
    before = _counts(rows)

    response = client.post(f"{PREFIX}/prompts/try", json=_try_body())

    assert response.status_code == 200, response.text
    report = response.json()
    assert [c["seq"] for c in report["chunks"]] == [0, 1, 2]
    assert all(c["status"] == "succeeded" for c in report["chunks"])
    assert report["chunks"][0]["items"] == ["a new claim"]
    assert report["chunks"][0]["text"] == "Paper one chunk 0"
    baseline = [c["baseline"] for c in report["chunks"]]
    assert baseline[0] == {
        "status": "succeeded",
        "items": ["old claim one", "old claim two"],
        "error": None,
    }
    assert baseline[1]["status"] == "failed"
    assert baseline[1]["error"] == "rate limited"
    assert baseline[2]["status"] == "not_run"
    assert sorted(model["current"].prompts) == [
        "Draft Paper one chunk 0",
        "Draft Paper one chunk 1",
        "Draft Paper one chunk 2",
    ]
    assert rows.writes == []
    assert _counts(rows) == before


def test_a_saved_version_can_be_tried_on_the_first_chunks(env):
    client, rows, model = env

    response = client.post(
        f"{PREFIX}/prompts/try",
        json=_try_body(draft=None, prompt_id=NEW.prompt_id, seqs=None, first=2),
    )

    assert response.status_code == 200, response.text
    assert [c["seq"] for c in response.json()["chunks"]] == [0, 1]
    assert response.json()["prompt_id"] == NEW.prompt_id
    assert model["current"].prompts[0].startswith("New ")
    assert rows.writes == []


def test_unusable_model_output_is_shown_with_the_raw_answer_and_writes_nothing(env):
    client, rows, model = env
    model["current"] = FakeModel("Sorry, I cannot help with that.")

    report = client.post(f"{PREFIX}/prompts/try", json=_try_body(seqs=[0])).json()

    chunk = report["chunks"][0]
    assert chunk["status"] == "failed"
    assert "not JSON" in chunk["error"]
    assert chunk["raw_output"] == "Sorry, I cannot help with that."
    assert rows.writes == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"seqs": list(range(11))}, "at most 10 chunks"),
        (
            {
                "draft": {
                    "name": "Claims",
                    "template": "No text",
                    "output_key": "results",
                }
            },
            "{chunk_text}",
        ),
        (
            {
                "draft": {
                    "name": "Claims",
                    "template": "{chunk_text}",
                    "output_key": "x",
                }
            },
            "output_key",
        ),
        ({"model_id": "nobody/nothing"}, "Unknown model"),
        ({"paper_id": "p2"}, "has not been chunked with"),
        ({"paper_id": "p3"}, "has not been ingested"),
        ({"seqs": [9]}, "no chunk 9"),
        ({"seqs": None, "first": 0}, "first"),
        ({"prompt_id": NEW.prompt_id}, "either a draft or a saved"),
        ({"draft": None}, "either a draft or a saved"),
    ],
)
def test_a_try_that_cannot_run_is_refused_with_a_clear_message(env, change, message):
    client, rows, model = env

    response = client.post(f"{PREFIX}/prompts/try", json=_try_body(**change))

    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert model["current"].prompts == []
    assert rows.writes == []


def test_trying_needs_a_signed_in_user(env):
    client, _, model = env

    response = client.post(
        f"{PREFIX}/prompts/try", json=_try_body(), headers={"Authorization": ""}
    )

    assert response.status_code in (401, 403)
    assert model["current"].prompts == []


def test_without_a_model_factory_trying_is_unavailable(dataset):
    service = PipelineAppService(
        DatasetRequestStore(DatasetRowStore(dataset)), rows=DatasetRowStore(dataset)
    )

    from phases_v2.app.pipeline_management import ManagementUnavailable

    with pytest.raises(ManagementUnavailable):
        service.try_prompt(_try_body())


# -- versions ---------------------------------------------------------------------


def test_versions_list_every_text_under_a_name_newest_first_with_their_use(env):
    client, _, _ = env

    body = client.get(f"{PREFIX}/prompts/versions?name=Claims").json()

    assert [v["prompt_id"] for v in body["versions"]] == [
        NEW.prompt_id,
        OLD.prompt_id,
    ]
    new, old = body["versions"]
    assert new["template"] == "New {chunk_text}"
    assert (new["run_count"], new["request_count"], new["item_count"]) == (0, 0, 0)
    assert old["registered_at"].startswith("2026-01-01")
    assert old["run_count"] == 1
    assert old["runs"][0]["request_id"] == "req-1"
    assert old["runs"][0]["model_id"] == MODEL
    assert old["request_count"] == 1
    assert old["requests"][0]["requested_by"] == "member@example.org"
    assert old["item_count"] == 3
    assert old["by_model"][MODEL] == {"items": 2, "succeeded": 1, "failed": 1}
    assert old["by_model"][OTHER_MODEL] == {"items": 1, "succeeded": 1, "failed": 0}


def test_versions_of_an_unknown_name_are_not_found(env):
    client, _, _ = env

    response = client.get(f"{PREFIX}/prompts/versions?name=Nobody")

    assert response.status_code == 404
    assert "Nobody" in response.json()["detail"]


def test_versions_include_the_prompts_declared_in_code(env):
    client, _, _ = env

    body = client.get(f"{PREFIX}/prompts/versions?name=solitude_what").json()

    assert body["versions"][0]["declared"] is True


def test_versions_are_ordered_by_first_appearance_not_by_a_later_restart(env):
    client, _, _ = env

    body = client.get(f"{PREFIX}/prompts/versions?name=Effects").json()

    assert [v["prompt_id"] for v in body["versions"]] == [
        LATER.prompt_id,
        RESTARTED.prompt_id,
    ]
    assert body["versions"][1]["first_seen"].startswith("2026-01-01")
    assert body["versions"][0]["first_seen"].startswith("2026-05-01")
