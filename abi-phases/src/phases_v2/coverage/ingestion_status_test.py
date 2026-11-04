"""The command: its flags, its exit codes and its JSON."""

import io
import json

import pytest

from phases_v2.coverage import factory
from phases_v2.coverage import ingestion_status as command
from phases_v2.coverage.domain import build_report
from phases_v2.coverage.domain_test import CURRENT, DECLARED, corpus

GPT = "openai/gpt-4.1-mini"


@pytest.fixture
def reader(monkeypatch):
    """The report reads this fake instead of the datasets."""
    fake = corpus()

    def report(dataset, object_storage, chosen):
        assert (dataset, object_storage) == ("dataset", "storage")
        return build_report(fake, chosen, declared=DECLARED, current=CURRENT)

    monkeypatch.setattr(factory, "coverage_report", report)
    return fake


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = command.main(
        list(argv), dataset="dataset", object_storage="storage", out=out, err=err
    )
    return code, out.getvalue(), err.getvalue()


def prompt_flags():
    return [arg for p in CURRENT for arg in ("--prompt-id", p.prompt_id)]


def test_strict_passes_on_a_complete_corpus(reader):
    code, out, _ = run("--strict", *prompt_flags(), "--chunker-id", "window_1_test")

    assert code == 0
    assert "Strict check: passed" in out


def test_strict_fails_when_chunks_were_not_run(reader):
    reader.chunks.append(
        {"chunk_id": "late", "paper_id": "a" * 64, "chunker_id": "window_1_test"}
    )

    code, out, _ = run("--strict", *prompt_flags(), "--chunker-id", "window_1_test")

    assert code == 1
    assert "chunks not run" in out


def test_without_strict_outstanding_work_still_exits_zero(reader):
    reader.chunks.append(
        {"chunk_id": "late", "paper_id": "a" * 64, "chunker_id": "window_1_test"}
    )

    code, _, _ = run(*prompt_flags(), "--chunker-id", "window_1_test")

    assert code == 0


def test_strict_ignores_invalid_answers(reader):
    row = next(e for e in reader.extractions if e["prompt_id"] == CURRENT[1].prompt_id)
    row.update(
        status="failed", raw_response='{"x": 1}', error="invalid RelationsOutput"
    )
    # An invalid answer has no items to project.
    reader.items = [i for i in reader.items if i["prompt_id"] != CURRENT[1].prompt_id]

    code, _, _ = run("--strict", *prompt_flags(), "--chunker-id", "window_1_test")

    assert code == 0


def test_json_shape(reader):
    code, out, _ = run(
        "--", "--json", *prompt_flags(), "--chunker-id", "window_1_test", "--model", GPT
    )

    data = json.loads(out)
    assert code == 0
    assert set(data) == {
        "snapshot",
        "selection",
        "sources",
        "failures",
        "prompt_versions",
        "undeclared_prompts",
        "run_requests",
        "projection_backlog",
        "relation_check",
        "strict",
    }
    assert data["selection"]["models"] == [GPT]
    source = data["sources"][0]
    assert set(source) == {
        "kind",
        "ids",
        "names",
        "pdfs",
        "not_ingested",
        "not_chunked",
        "unsupported_files",
        "unreadable_members",
        "not_ingested_pdfs",
        "not_chunked_papers",
        "coverage",
    }
    assert set(source["coverage"][0]) == {
        "prompt_id",
        "prompt_name",
        "model_id",
        "chunks",
        "succeeded",
        "failed_calls",
        "invalid_answers",
        "not_run",
    }
    assert source["coverage"][0]["failed_calls"] == {"total": 0, "by_reason": {}}
    assert set(data["projection_backlog"]) == {
        "graph",
        "vector_chunks",
        "vector_items",
        "probabilistic_relations_v1",
    }
    assert data["strict"] == {"passed": True, "problems": []}


def test_an_unknown_prompt_id_exits_two(reader):
    code, out, err = run("--prompt-id", "nope")

    assert (code, out) == (2, "")
    assert "nope" in err
