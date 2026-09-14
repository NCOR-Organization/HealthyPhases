"""Quoted keyword semantics through the production SQL and HTTP paths."""

import csv
import io

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from phases_v2.app.adapters.primary.SearchAPI import PREFIX, register
from phases_v2.search.adapters.secondary.DatasetExtractedItemsAdapter import (
    DatasetExtractedItemsAdapter,
)
from phases_v2.search.domain import SearchService
from phases_v2.search.fakes import FakeSemanticIndex
from phases_v2.search.search_keywords import matches_term, tokenize

TEXTS = [
    "I like solitude and stress research.",
    "Likely stress and dislike.",
    "People around stress.",
    "People surround stress.",
    "Being alone reduces stress.",
    "Being happily alone reduces stress.",
    "Alone being around stress.",
    "Being\nalone reduces stress.",
    "100% around (x+y).",
    "1000 around xxy.",
    "élike around_person",
    "LIKE stress.",
]


class Rows:
    def __init__(self):
        self.db = duckdb.connect(":memory:")
        self.db.execute(
            "CREATE TABLE extracted_items(item_id VARCHAR, text VARCHAR, prompt_id VARCHAR, extraction_id VARCHAR, chunk_id VARCHAR, paper_id VARCHAR)"
        )
        self.db.execute(
            "CREATE TABLE extractions(extraction_id VARCHAR, model_id VARCHAR)"
        )
        self.db.execute(
            "CREATE TABLE chunks(chunk_id VARCHAR, seq INTEGER, text VARCHAR)"
        )
        self.db.execute(
            "CREATE TABLE papers(paper_id VARCHAR, file_name VARCHAR, storage_prefix VARCHAR, storage_key VARCHAR)"
        )
        self.db.execute(
            "CREATE TABLE prompts(prompt_id VARCHAR, name VARCHAR, template VARCHAR)"
        )
        self.db.execute(
            "INSERT INTO extractions VALUES ('e','model'); INSERT INTO chunks VALUES ('c',0,'context'); INSERT INTO papers VALUES ('p','a.pdf','phases_v2','a.pdf'); INSERT INTO prompts VALUES ('pr','effects','prompt')"
        )
        self.db.executemany(
            "INSERT INTO extracted_items VALUES (?,?,'pr','e','c','p')",
            [(str(i).zfill(2), text) for i, text in enumerate(TEXTS)],
        )

    def query(self, sql):
        result = self.db.execute(sql)
        names = [column[0] for column in result.description]
        return [dict(zip(names, row)) for row in result.fetchall()]

    def snapshot(self):
        return None

    def at_snapshot(self, snapshot):
        return self


@pytest.fixture
def service():
    rows = Rows()
    yield SearchService(FakeSemanticIndex(), DatasetExtractedItemsAdapter(rows))
    rows.db.close()


@pytest.mark.parametrize(
    "query, expected",
    [
        ('"like"', [0, 11]),
        ("like", [0, 1, 10, 11]),
        ('"around"', [2, 6, 8, 9]),
        ('"being alone" stress', [4, 7]),
        ('"being alone" "stress"', [4, 7]),
        ("being alone stress", [4, 5, 6, 7]),
        ('"100%"', [8]),
        ('"around (x+y)"', [8]),
        ("\u201clike\u201d", [0, 11]),
        ('""', []),
        ('"missing"', []),
        ('"like\' OR 1=1 --"', []),
    ],
)
def test_exact_matching_in_sql_and_fake_port_agree(service, query, expected):
    hits, count = service.page("keyword", query, limit=100)
    assert [int(hit.item_id) for hit in hits] == expected
    assert count == len(expected)
    assert [
        i
        for i, text in enumerate(TEXTS)
        if tokenize(query) and all(matches_term(text, term) for term in tokenize(query))
    ] == expected


def test_quotes_are_preserved_and_bare_words_keep_existing_tokenization():
    assert tokenize('Stress "being alone" STRESS "like"') == [
        "stress",
        '"being alone"',
        '"like"',
    ]
    assert tokenize('"" "   "') == []
    assert tokenize('"unfinished quote') == ["unfinished", "quote"]


def test_http_pagination_filters_and_export_use_the_same_phrase_matches(service):
    app = FastAPI()
    register(app, service)
    client = TestClient(app)
    params = {
        "q": '"being alone" stress',
        "limit": 1,
        "prompt": "effects",
        "model": "model",
        "path": "phases_v2",
    }
    first = client.get(f"{PREFIX}/keyword", params=params).json()
    assert first["total"] == 2
    assert first["hits"][0]["item_id"] == "04"
    second = client.get(
        f"{PREFIX}/keyword", params={**params, "offset": first["next_offset"]}
    ).json()
    assert second["total"] == 2
    assert second["hits"][0]["item_id"] == "07"
    assert not second["has_more"]
    response = client.get(f"{PREFIX}/export", params={**params, "mode": "keyword"})
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert [row["item_id"] for row in rows] == ["04", "07"]
    assert (
        client.get(f"{PREFIX}/keyword", params={**params, "prompt": "missing"}).json()[
            "total"
        ]
        == 0
    )
