"""Regression for the dictionary representation found in production results."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from phases_v2.app.adapters.primary.SearchAPI import PREFIX, register
from phases_v2.search.domain import SearchService
from phases_v2.search.fakes import FakeExtractedItems, FakeItem, FakeSemanticIndex
from phases_v2.search.models import ItemLocation
from phases_v2.search.search_payloads import canonical_payload_text

RELATION = {
    "subject_process": "spending less time alone than desired",
    "subject_participant": "person with unmet solitude preference",
    "target_process": "experiencing stress and depression",
    "direction": "increases",
    "evidence_text": "spending less time alone than one would like is associated with increased stress and depression",
}


@pytest.mark.parametrize("mode", ["semantic", "keyword"])
def test_actual_legacy_result_is_returned_as_renderable_json(mode):
    original = str(RELATION)
    item = FakeItem(
        "legacy", original, ItemLocation(prompt_name="probabilistic_processes")
    )
    app = FastAPI()
    register(app, SearchService(FakeSemanticIndex([item]), FakeExtractedItems([item])))
    response = TestClient(app).get(f"{PREFIX}/{mode}", params={"q": "stress"})
    assert response.status_code == 200
    assert json.loads(response.json()["hits"][0]["extracted_text"]) == RELATION
    assert item.text == original  # No rewrite or re-extraction of the corpus.


@pytest.mark.parametrize("payload", [RELATION, [RELATION], {"relations": [RELATION]}])
def test_legacy_payload_shapes_are_supported(payload):
    assert json.loads(canonical_payload_text(str(payload))) == payload


def test_quotes_backslashes_and_unicode_are_preserved():
    payload = {
        **RELATION,
        "evidence_text": 'A person\'s "alone time"\nC:\\papers\\study - solitude \u2014 stress',
    }
    assert json.loads(canonical_payload_text(str(payload))) == payload


@pytest.mark.parametrize(
    "text",
    [
        "Ordinary claim",
        "{invalid",
        "{'not-json-set'}",
        "{'bytes': b'text'}",
        '{"already": "JSON"}',
        "[" * 300,
        "{" + "x" * 65536,
    ],
)
def test_ordinary_valid_or_unsupported_text_is_unchanged(text):
    assert canonical_payload_text(text) == text


def test_expressions_are_never_executed(tmp_path):
    marker = tmp_path / "must-not-exist"
    text = (
        "{'subject_process': __import__('pathlib').Path("
        + repr(str(marker))
        + ").touch()}"
    )
    assert canonical_payload_text(text) == text
    assert not marker.exists()
