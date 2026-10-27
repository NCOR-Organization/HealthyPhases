"""Results per paper: the papers list and one paper's page, on real datasets.

A DuckLake store holds the pipeline's tables next to the PubMed library and
OpenAlex enrichment, written through those modules' own stores, so the joins by
content hash and PMID run as they do in production.
"""

import csv
import io
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from openalex.adapters.secondary.openalex_dataset_store import OpenalexDatasetStore
from phases_v2 import identity
from phases_v2.app.adapters.primary.PipelineAPI import PREFIX, register
from phases_v2.app.adapters.primary.SearchAPI import CSV_COLUMNS
from phases_v2.app.paper_links import PaperFacts, RequestScope
from phases_v2.app.service import PipelineAppService
from phases_v2.chunking.chunkers import WINDOW_512_128
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.store import ensure_datasets
from phases_v2.prompts.domain import PromptTemplate
from phases_v2.requests.adapters.secondary.DatasetRequestStore import (
    DatasetRequestStore,
)
from phases_v2.sources.library_links import is_published_pdf, linked_schemas
from pubmed.adapters.secondary.pubmed_dataset_store import PubmedDatasetStore

CHUNKER = WINDOW_512_128.chunker_id
M1 = "openai/gpt-4.1-mini"
M2 = "openai/gpt-5-mini"
CLAIMS_V1 = PromptTemplate("claims", "First {chunk_text}", "results")
CLAIMS_V2 = PromptTemplate("claims", "Second {chunk_text}", "results")
EFFECTS = PromptTemplate("effects", "Effects {chunk_text}", "relations")

# From PubMed, with results from several versions and models.
PUBMED_PDF = "a" * 64
# An uploaded file under a folder, run once, nothing found.
UPLOADED = "b" * 64
# Ingested and never run.
UNTOUCHED = "c" * 64
# Recorded, but its text could not be read.
UNREADABLE = "d" * 64
TITLE = "Solitude and stress in older adults"


def at(month, day=1):
    return datetime(2026, month, day, tzinfo=UTC)


def chunk(paper, seq):
    return identity.chunk_id(paper, CHUNKER, seq)


def extraction(paper, seq, model, prompt, status="succeeded", run="", **extra):
    return {
        "extraction_id": identity.extraction_id(
            chunk(paper, seq), model, prompt.prompt_id
        ),
        "chunk_id": chunk(paper, seq),
        "model_id": model,
        "prompt_id": prompt.prompt_id,
        "run_id": run or None,
        "status": status,
        "completed_at": at(4),
        **extra,
    }


def item(paper, seq, model, prompt, index, text):
    extraction_id = identity.extraction_id(chunk(paper, seq), model, prompt.prompt_id)
    return {
        "item_id": identity.item_id(extraction_id, index),
        "extraction_id": extraction_id,
        "chunk_id": chunk(paper, seq),
        "paper_id": paper,
        "prompt_id": prompt.prompt_id,
        "seq": index,
        "text": text,
    }


RELATION = {
    "subject_process": "spending time alone",
    "subject_participant": "older adults",
    "target_process": "stress",
    "direction": "decreases",
    "evidence_text": "Time alone lowered reported stress.",
}


def _seed(rows):
    rows.write_rows(
        "papers",
        [
            {
                "paper_id": PUBMED_PDF,
                "content_sha256": PUBMED_PDF,
                "file_name": f"{PUBMED_PDF}.pdf",
                "storage_prefix": "pubmed/papers",
                "storage_key": f"PMC1/{PUBMED_PDF}.pdf",
                "text_key": "a.md",
                "discovered_at": at(1),
            },
            {
                "paper_id": UPLOADED,
                "content_sha256": UPLOADED,
                "file_name": "Being alone.pdf",
                "storage_prefix": "phases_v2/solitude",
                "storage_key": "Being alone.pdf",
                "text_key": "b.md",
                "discovered_at": at(2),
            },
            {
                "paper_id": UNTOUCHED,
                "content_sha256": UNTOUCHED,
                "file_name": "Zebra finches.pdf",
                "storage_prefix": "phases_v2/other",
                "storage_key": "Zebra finches.pdf",
                "text_key": "c.md",
                "discovered_at": at(5),
            },
            {
                "paper_id": UNREADABLE,
                "content_sha256": UNREADABLE,
                "file_name": "Scanned.pdf",
                "storage_prefix": "phases_v2/solitude",
                "storage_key": "Scanned.pdf",
                "text_key": None,
                "discovered_at": at(2),
            },
        ],
    )
    rows.write_rows(
        "paper_paths",
        [
            {
                "path": "phases_v2/copies/Being alone.pdf",
                "paper_id": UPLOADED,
                "seen_at": at(2),
            }
        ],
    )
    rows.write_rows(
        "chunks",
        [
            {
                "chunk_id": chunk(paper, seq),
                "paper_id": paper,
                "chunker_id": CHUNKER,
                "seq": seq,
                "text": f"{paper[0]} chunk {seq} text",
            }
            for paper, count in ((PUBMED_PDF, 3), (UPLOADED, 2), (UNTOUCHED, 1))
            for seq in range(count)
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
            for p, month in ((CLAIMS_V1, 1), (CLAIMS_V2, 3), (EFFECTS, 1))
        ],
    )
    rows.write_rows(
        "extractions",
        [
            extraction(
                PUBMED_PDF, 0, M1, CLAIMS_V1, run=f"r-pubmed:{CLAIMS_V1.prompt_id}"
            ),
            extraction(
                PUBMED_PDF,
                1,
                M1,
                CLAIMS_V1,
                status="failed",
                run=f"r-pubmed:{CLAIMS_V1.prompt_id}",
                error="The output was not valid JSON.",
                raw_response="{not json" + "x" * 700,
            ),
            extraction(PUBMED_PDF, 0, M1, CLAIMS_V2),
            extraction(PUBMED_PDF, 1, M2, CLAIMS_V1),
            extraction(PUBMED_PDF, 2, M1, EFFECTS, run=f"r-pubmed:{EFFECTS.prompt_id}"),
            extraction(
                UPLOADED, 0, M1, CLAIMS_V1, run=f"r-folder:{CLAIMS_V1.prompt_id}"
            ),
        ],
    )
    effect = item(PUBMED_PDF, 2, M1, EFFECTS, 0, '{"relations": []}')
    rows.write_rows(
        "extracted_items",
        [
            item(PUBMED_PDF, 0, M1, CLAIMS_V1, 0, "Solitude lowers stress"),
            item(PUBMED_PDF, 0, M1, CLAIMS_V1, 1, "Older adults seek time alone"),
            item(PUBMED_PDF, 0, M1, CLAIMS_V2, 0, "Solitude lowers stress"),
            item(PUBMED_PDF, 1, M2, CLAIMS_V1, 0, "Loneliness differs from solitude"),
            effect,
        ],
    )
    rows.write_rows(
        "probabilistic_relations",
        [
            {
                "relation_id": "rel-1",
                "item_id": effect["item_id"],
                "relation_index": 0,
                "extraction_id": effect["extraction_id"],
                "chunk_id": effect["chunk_id"],
                "paper_id": PUBMED_PDF,
                "prompt_id": EFFECTS.prompt_id,
                "model_id": M1,
                **RELATION,
            }
        ],
    )
    request = {
        "chunker_id": CHUNKER,
        "model_id": M1,
        "requested_by": "member@example.org",
    }
    rows.write_rows(
        "run_requests",
        [
            dict(
                request,
                request_id="r-pubmed",
                status="succeeded",
                locations=["dataset:pubmed:q1"],
                prompt_ids=[CLAIMS_V1.prompt_id, EFFECTS.prompt_id],
                requested_at=at(4),
                finished_at=at(4, 2),
            ),
            # Covers the uploaded paper by its folder, before the untouched one existed.
            dict(
                request,
                request_id="r-folder",
                status="succeeded",
                locations=["phases_v2/solitude"],
                prompt_ids=[CLAIMS_V1.prompt_id],
                requested_at=at(3),
                finished_at=at(3, 2),
            ),
            # Over everything, but finished before any of these papers was found.
            dict(
                request,
                request_id="r-early",
                status="failed",
                locations=["phases_v2"],
                prompt_ids=[CLAIMS_V1.prompt_id],
                requested_at=at(1),
                finished_at=at(1),
            ),
            # Its manifest names the uploaded paper's copy by path.
            dict(
                request,
                request_id="r-copy",
                status="pending",
                locations=["dataset:collection:c1"],
                prompt_ids=[CLAIMS_V2.prompt_id],
                requested_at=at(6),
            ),
        ],
    )
    rows.write_rows(
        "source_manifests",
        [
            {
                "request_id": "r-pubmed",
                "source_query_id": "q1",
                "artifacts": [
                    {
                        "storage_prefix": "pubmed/papers",
                        "storage_key": f"PMC1/{PUBMED_PDF}.pdf",
                        "content_sha256": PUBMED_PDF,
                        "artifact_id": f"111:{PUBMED_PDF}",
                    }
                ],
            },
            {
                "request_id": "r-copy",
                "source_query_id": "c1",
                "artifacts": [
                    {
                        "storage_prefix": "phases_v2/copies",
                        "storage_key": "Being alone.pdf",
                        "content_sha256": "",
                        "artifact_id": "",
                    }
                ],
            },
        ],
    )


def _seed_pubmed(dataset):
    store = PubmedDatasetStore(dataset)
    store.ensure()
    store.save(
        "papers",
        [
            {
                "pmid": "111",
                "pmcid": "PMC1",
                "doi": "10.1000/solitude",
                "title": TITLE,
                "journal": "Journal of Ageing",
                "publication_date": "2024 Mar",
                "authors": ["Ada Byron", "Alan Turing"],
            }
        ],
    )
    store.save(
        "artifacts",
        [
            {
                "artifact_id": f"111:{PUBMED_PDF}",
                "pmid": "111",
                "pmcid": "PMC1",
                "version": "1",
                "status": "ready",
                "storage_prefix": "pubmed/papers",
                "storage_key": f"PMC1/{PUBMED_PDF}.pdf",
                "content_sha256": PUBMED_PDF,
                "size_bytes": 10,
                "source_url": "https://example.org/a.pdf",
                "contract_version": 1,
            }
        ],
    )
    openalex = OpenalexDatasetStore(dataset)
    openalex.ensure()
    openalex.save(
        "paper_enrichments",
        [
            {
                "pmid": "111",
                "status": "enriched",
                "work_id": "W1",
                "matched_by": "doi",
                "citation_count": 42,
                "topics": ["Ageing"],
                "institutions": ["University of Buffalo"],
                "contract_version": 1,
            }
        ],
    )
    openalex.save(
        "works",
        [
            {
                "work_id": "W1",
                "pmid": "111",
                "title": TITLE,
                "citation_count": 42,
                "topics": [{"id": "T1", "name": "Ageing", "score": 0.9}],
                "locations": [
                    {"landing_page_url": "https://example.org/a", "is_oa": True}
                ],
                "is_oa": True,
                "oa_status": "gold",
                "contract_version": 1,
            }
        ],
    )


def _dataset(path, with_library):
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{path / 'catalog.sqlite'}",
            data_path=str(path / "warehouse") + "/",
        )
    )
    ensure_datasets(dataset)
    _seed(DatasetRowStore(dataset))
    if with_library:
        _seed_pubmed(dataset)
    return dataset


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    return _dataset(tmp_path_factory.mktemp("results"), with_library=True)


def _client(dataset, monkeypatch):
    monkeypatch.setenv("ABI_API_KEY", "test-pipeline-key")
    rows = DatasetRowStore(dataset)
    service = PipelineAppService(DatasetRequestStore(rows), rows=rows)
    app = FastAPI()
    register(app, service)
    client = TestClient(app, headers={"Authorization": "Bearer test-pipeline-key"})
    return client, service


@pytest.fixture
def env(dataset, monkeypatch):
    client, service = _client(dataset, monkeypatch)
    yield client, service
    client.close()


def ids(page):
    return [paper["paper_id"] for paper in page["papers"]]


def listed(client, query=""):
    response = client.get(f"{PREFIX}/papers?{query}")
    assert response.status_code == 200, response.text
    return response.json()


# -- the list ---------------------------------------------------------------------


def test_each_paper_is_titled_counted_and_located(env):
    client, _ = env

    page = listed(client)

    # PubMed titles sort with file names: "Being alone", "Solitude...", "Zebra...".
    assert ids(page) == [UPLOADED, PUBMED_PDF, UNTOUCHED]
    assert page["total"] == 3
    uploaded, from_pubmed, untouched = page["papers"]
    assert from_pubmed["title"] == TITLE
    assert from_pubmed["pmid"] == "111"
    assert from_pubmed["source"] == "pubmed"
    assert from_pubmed["path"] == f"pubmed/papers/PMC1/{PUBMED_PDF}.pdf"
    assert from_pubmed["chunks"] == {CHUNKER: 3}
    assert from_pubmed["extractions"] == {"succeeded": 4, "failed": 1}
    assert from_pubmed["items"] == {"claims": 4, "effects": 1}
    assert from_pubmed["item_count"] == 5
    assert uploaded["title"] == "Being alone.pdf"
    assert uploaded["source"] == "file"
    assert uploaded["discovered_at"].startswith("2026-02-01")
    assert uploaded["extractions"] == {"succeeded": 1, "failed": 0}
    assert uploaded["items"] == {}
    assert untouched["extractions"] == {"succeeded": 0, "failed": 0}
    assert untouched["item_count"] == 0


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        # The PubMed title, the PMID, the file name and the folder all find a paper.
        ("q=STRESS", [PUBMED_PDF]),
        ("q=111", [PUBMED_PDF]),
        ("q=being", [UPLOADED]),
        ("q=phases_v2/other", [UNTOUCHED]),
        ("prompt=effects", [PUBMED_PDF]),
        ("prompt=claims", [UPLOADED, PUBMED_PDF]),
        (f"prompt_id={CLAIMS_V2.prompt_id}", [PUBMED_PDF]),
        (f"model={M2}", [PUBMED_PDF]),
        ("has_results=true", [PUBMED_PDF]),
        # Papers without results include the ones never run.
        ("has_results=false", [UPLOADED, UNTOUCHED]),
        # With a prompt chosen, only the papers it ran on and found nothing in.
        ("prompt=claims&has_results=false", [UPLOADED]),
        (f"paper_id={UNTOUCHED}&paper_id={UNREADABLE}", [UNTOUCHED]),
        ("request_id=r-pubmed", [PUBMED_PDF]),
        ("request_id=r-folder", [UPLOADED]),
        ("request_id=r-copy", [UPLOADED]),
        ("request_id=r-early", []),
        ("sort=newest", [UNTOUCHED, UPLOADED, PUBMED_PDF]),
        ("sort=oldest", [PUBMED_PDF, UPLOADED, UNTOUCHED]),
    ],
)
def test_the_list_filters_and_sorts(env, query, expected):
    client, _ = env

    assert ids(listed(client, query)) == expected


def test_counts_follow_the_chosen_prompt_and_model(env):
    client, _ = env

    [paper] = listed(client, f"prompt=claims&model={M1}&q=111")["papers"]

    assert paper["items"] == {"claims": 3}
    assert paper["extractions"] == {"succeeded": 2, "failed": 1}


def test_pages_are_stable_and_cover_every_paper_once(env):
    client, _ = env

    seen = []
    for offset in range(4):
        page = listed(client, f"limit=1&offset={offset}&sort=newest")
        assert page["total"] == 3
        seen += ids(page)

    assert seen == [UNTOUCHED, UPLOADED, PUBMED_PDF]


def test_a_collection_lists_its_ingested_papers(env, monkeypatch):
    client, service = env
    asked = []

    def paper_ids(collection_id):
        asked.append(collection_id)
        return [PUBMED_PDF, UNREADABLE, "not-yet-ingested"]

    monkeypatch.setattr(service.resources, "paper_ids", paper_ids)
    collection = "0b8f2c1e-1111-4222-8333-944445555666"

    assert ids(listed(client, f"collection={collection}")) == [PUBMED_PDF]
    assert ids(listed(client, f"collection={collection}&paper_id={UPLOADED}")) == []
    assert asked == [collection, collection]


def test_an_empty_collection_lists_nothing(env, monkeypatch):
    client, service = env
    monkeypatch.setattr(service.resources, "paper_ids", lambda _: [])

    page = listed(client, "collection=0b8f2c1e-1111-4222-8333-944445555666")

    assert page["papers"] == [] and page["total"] == 0


@pytest.mark.parametrize(
    ("query", "status"),
    [
        ("request_id=nope", 404),
        ("sort=sideways", 422),
        ("collection=not-a-collection", 422),
        ("limit=500", 422),
    ],
)
def test_bad_filters_are_refused(env, query, status):
    client, _ = env

    assert client.get(f"{PREFIX}/papers?{query}").status_code == status


def test_without_the_pubmed_library_papers_are_titled_by_file_name(
    tmp_path, monkeypatch
):
    client, _ = _client(_dataset(tmp_path, with_library=False), monkeypatch)

    page = listed(client)
    detail = client.get(f"{PREFIX}/papers/{PUBMED_PDF}").json()

    assert [p["title"] for p in page["papers"]] == [
        f"{PUBMED_PDF}.pdf",
        "Being alone.pdf",
        "Zebra finches.pdf",
    ]
    assert page["papers"][0]["source"] == "file"
    assert detail["pubmed"] is None and detail["openalex"] is None
    assert detail["paper"]["title"] == f"{PUBMED_PDF}.pdf"
    client.close()


# -- one paper --------------------------------------------------------------------


def test_a_pubmed_paper_carries_its_library_and_openalex_records(env):
    client, _ = env

    detail = client.get(f"{PREFIX}/papers/{PUBMED_PDF}").json()

    assert detail["paper"]["title"] == TITLE
    assert detail["paper"]["pmid"] == "111"
    assert detail["paper"]["ingested"] is True
    assert detail["pubmed"]["doi"] == "10.1000/solitude"
    assert detail["pubmed"]["authors"] == ["Ada Byron", "Alan Turing"]
    assert detail["openalex"]["enrichment"]["citation_count"] == 42
    assert detail["openalex"]["work"]["oa_status"] == "gold"
    assert detail["openalex"]["work"]["topics"][0]["name"] == "Ageing"
    assert detail["chunkers"] == [{"chunker_id": CHUNKER, "chunks": 3}]


def test_results_are_grouped_by_prompt_version_and_model(env):
    client, _ = env

    detail = client.get(f"{PREFIX}/papers/{PUBMED_PDF}").json()
    groups = detail["results"]

    # By prompt name, then model; the newer version of a name first.
    assert [(g["prompt_id"], g["model_id"]) for g in groups] == [
        (CLAIMS_V2.prompt_id, M1),
        (CLAIMS_V1.prompt_id, M1),
        (CLAIMS_V1.prompt_id, M2),
        (EFFECTS.prompt_id, M1),
    ]
    assert [g["prompt_id"] for g in detail["ran"]] == [g["prompt_id"] for g in groups]
    first = groups[1]
    assert first["prompt_name"] == "claims"
    assert first["template"] == CLAIMS_V1.template
    assert (first["succeeded"], first["failed"], first["item_count"]) == (1, 1, 2)
    assert first["request_ids"] == ["r-pubmed"]
    assert [(i["chunk_seq"], i["text"]) for i in first["items"]] == [
        (0, "Solitude lowers stress"),
        (0, "Older adults seek time alone"),
    ]
    [failure] = first["failures"]
    assert failure["seq"] == 1
    assert failure["error"] == "The output was not valid JSON."
    assert failure["raw_excerpt"].startswith("{not json")
    assert failure["raw_excerpt"].endswith("…")
    # Each item's chunk is sent once, with its text.
    chunk_of = detail["chunks"][first["items"][0]["chunk_id"]]
    assert (chunk_of["seq"], chunk_of["text"]) == (0, "a chunk 0 text")


def test_relations_come_with_the_item_that_carries_them(env):
    client, _ = env

    effects = client.get(f"{PREFIX}/papers/{PUBMED_PDF}").json()["results"][-1]

    assert effects["relation_count"] == 1
    [found] = effects["items"]
    assert found["chunk_seq"] == 2
    assert found["relations"] == [{"relation_id": "rel-1", **RELATION}]


def test_the_requests_that_included_a_paper_are_listed(env):
    client, _ = env

    def requests(paper):
        body = client.get(f"{PREFIX}/papers/{paper}").json()
        return [r["request_id"] for r in body["requests"]]

    assert requests(PUBMED_PDF) == ["r-pubmed"]
    # By folder, and by a manifest naming a copy at another path; newest first.
    assert requests(UPLOADED) == ["r-copy", "r-folder"]
    assert requests(UNTOUCHED) == []


def test_a_paper_without_results_still_opens(env):
    client, _ = env

    detail = client.get(f"{PREFIX}/papers/{UNTOUCHED}").json()

    assert detail["results"] == [] and detail["ran"] == []
    assert detail["chunkers"] == [{"chunker_id": CHUNKER, "chunks": 1}]
    assert detail["pubmed"] is None
    unreadable = client.get(f"{PREFIX}/papers/{UNREADABLE}").json()
    assert unreadable["paper"]["ingested"] is False


def test_a_run_with_nothing_found_shows_as_a_group_without_items(env):
    client, _ = env

    [group] = client.get(f"{PREFIX}/papers/{UPLOADED}").json()["results"]

    assert (group["succeeded"], group["item_count"], group["items"]) == (1, 0, [])
    assert group["request_ids"] == ["r-folder"]


def test_an_unknown_paper_is_a_404(env):
    client, _ = env

    assert client.get(f"{PREFIX}/papers/nope").status_code == 404


# -- the CSV export -----------------------------------------------------------------


def export(client, query=""):
    response = client.get(f"{PREFIX}/papers/{PUBMED_PDF}/export?{query}")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))


def test_the_export_has_the_search_columns_and_a_row_per_item_or_relation(env):
    client, _ = env

    rows = export(client)

    assert list(rows[0]) == CSV_COLUMNS
    assert len(rows) == 5
    assert {r["mode"] for r in rows} == {"paper"}
    relation = next(r for r in rows if r["relation_id"])
    assert relation["direction"] == "decreases"
    assert relation["prompt_name"] == "effects"
    claim = next(
        r for r in rows if r["extracted_text"] == "Older adults seek time alone"
    )
    assert claim["chunk_seq"] == "0"
    assert claim["chunk_text"] == "a chunk 0 text"
    assert claim["source_path"] == "pubmed/papers/PMC1"
    assert claim["prompt_template"] == CLAIMS_V1.template


def test_the_export_can_hold_one_version_or_one_model(env):
    client, _ = env

    assert len(export(client, f"prompt_id={CLAIMS_V2.prompt_id}")) == 1
    assert {r["model_id"] for r in export(client, f"model_id={M2}")} == {M2}


def test_exporting_an_unknown_paper_is_a_404(env):
    client, _ = env

    assert client.get(f"{PREFIX}/papers/nope/export").status_code == 404


# -- the request scope, without SQL -------------------------------------------------


def test_a_folder_request_does_not_claim_papers_found_after_it_finished():
    scope = RequestScope.of(
        {
            "request_id": "r",
            "locations": '["phases_v2/a"]',
            "prompt_ids": '["p"]',
            "finished_at": at(3),
        },
        None,
    )

    def paper(path, found):
        return PaperFacts.of(
            {
                "paper_id": "x",
                "storage_prefix": "",
                "storage_key": path,
                "discovered_at": found,
            },
            [],
            [],
        )

    assert scope.includes(paper("phases_v2/a/x.pdf", at(2)))
    assert not scope.includes(paper("phases_v2/a/x.pdf", at(4)))
    # A folder is a path component, not a prefix of a name.
    assert not scope.includes(paper("phases_v2/ab/x.pdf", at(2)))


def test_only_the_exact_published_object_counts_as_a_pubmed_pdf(dataset, tmp_path):
    rows = DatasetRowStore(dataset)
    schemas = linked_schemas(rows)
    published = ("pubmed/papers", f"PMC1/{PUBMED_PDF}.pdf")

    assert schemas == {"pubmed", "openalex"}
    assert is_published_pdf(rows, schemas, *published, PUBMED_PDF)
    assert not is_published_pdf(rows, schemas, *published, UPLOADED)
    assert not is_published_pdf(rows, schemas, "pubmed/papers", "other.pdf", PUBMED_PDF)
    bare = DatasetRowStore(_dataset(tmp_path, with_library=False))
    assert linked_schemas(bare) == set()
    assert not is_published_pdf(bare, set(), *published, PUBMED_PDF)
