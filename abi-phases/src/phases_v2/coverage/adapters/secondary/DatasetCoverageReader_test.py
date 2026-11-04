"""The coverage reader, against a real local dataset catalog.

The PubMed publisher runs for real against the same catalog, so saved searches
resolve through the catalog exactly as they do deployed. The same rows are
handed to the in-memory fake, and both must count them the same way.
"""

from hashlib import sha256

import pytest
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService
from naas_abi_core.services.object_storage.ObjectStoragePort import (
    Exceptions as StorageExceptions,
)

from phases_v2.coverage.adapters.secondary.DatasetCoverageReader import (
    DatasetCoverageReader,
    PinnedDataset,
)
from phases_v2.coverage.domain import build_report
from phases_v2.coverage.fakes import FakeCoverageReader
from phases_v2.coverage.interfaces import (
    COLLECTION,
    EVERYTHING,
    PUBMED_SEARCH,
    RELATIONS,
    Selection,
)
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.store import ensure_datasets
from phases_v2.extraction.interfaces import PROVIDER_FAILURE
from phases_v2.paper_collections.domain import folder_member, member_from_command
from phases_v2.prompts.domain import PromptTemplate
from phases_v2.sources.adapters.secondary.phases_v2_pubmed_catalog import PubmedCatalog
from pubmed.adapters.secondary.pubmed_dataset_store import PubmedDatasetStore
from pubmed.application.pubmed_service import PubmedService
from pubmed.tests.pubmed_service_test import FakeSource, MemoryStorage

GPT = "openai/gpt-4.1-mini"
CHUNKER = "window_1_test"
WHAT = PromptTemplate("solitude_what", "What? {chunk_text}", "what")
REL = PromptTemplate("probabilistic_processes", "Rel? {chunk_text}", "relations")
SELECTION = Selection((GPT,), (WHAT.prompt_id, REL.prompt_id), CHUNKER)

FOLDER_PDF = b"%PDF-1.7 solitude folder paper"
GERO_PDF = b"%PDF-1.7 gerotranscendence, never ingested"
PAPER_A = sha256(FOLDER_PDF).hexdigest()


class Storage(MemoryStorage):
    """Object storage that also lists, as the engine's service does."""

    def __init__(self):
        super().__init__()
        self.reads = 0

    def get_object(self, prefix, key):
        self.reads += 1
        return super().get_object(prefix, key)

    def list_objects_recursive(self, prefix):
        keys = [
            f"{p}/{k}" for p, k in self.files if f"{p}/{k}".startswith(prefix + "/")
        ]
        if not keys:
            raise StorageExceptions.ObjectNotFound(prefix)
        return keys


def _search(publisher, text):
    query = publisher.search({"query": text})["query"]
    request = publisher.submit({"query_id": query["query_id"]})
    publisher.execute(request["request_id"], "run")
    return query["query_id"]


def _extraction(chunk, prompt, status="succeeded", raw="{}", error=None):
    return {
        "extraction_id": f"{chunk}:{GPT}:{prompt.prompt_id}",
        "chunk_id": chunk,
        "model_id": GPT,
        "prompt_id": prompt.prompt_id,
        "status": status,
        "raw_response": raw,
        "error": error,
    }


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    # Building the catalog and publishing PubMed papers is the slow part, so
    # the corpus is built once; the one test that writes adds a row no other
    # test reads.
    tmp_path = tmp_path_factory.mktemp("coverage")
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{tmp_path / 'catalog.sqlite'}",
            data_path=str(tmp_path / "warehouse") + "/",
        )
    )
    PubmedDatasetStore(dataset).ensure()
    ensure_datasets(dataset)
    storage = Storage()
    publisher = PubmedService(PubmedDatasetStore(dataset), FakeSource(), storage)
    # The same search saved twice resolves to the same PDFs.
    first, second = _search(publisher, "solitude"), _search(publisher, "solitude")
    pubmed = PubmedCatalog(dataset).artifacts(first)
    paper_b = pubmed[1]["content_sha256"]

    storage.put_object("phases_v2/solitude", "a.pdf", FOLDER_PDF)
    # The same content as a PubMed PDF, in a folder nothing ingested.
    storage.put_object(
        "phases_v2/solitude",
        "copy-of-2.pdf",
        storage.get_object(pubmed[1]["storage_prefix"], pubmed[1]["storage_key"]),
    )
    storage.put_object("phases_v2/solitude", "notes.txt", b"not a paper")
    storage.put_object("phases_v2/gerotranscendence", "g.pdf", GERO_PDF)

    rows = DatasetRowStore(dataset)
    rows.write_rows(
        "input_collections",
        [
            {
                "collection_id": "gero",
                "name": "gerotranscendence uploaded papers",
                "locations": ["phases_v2/gerotranscendence"],
                "archived": False,
            },
            {
                "collection_id": "gone",
                "name": "archived",
                "locations": ["phases_v2/solitude"],
                "archived": True,
            },
        ],
    )
    rows.write_rows(
        "paper_collections",
        [
            {
                "collection_id": "mixed",
                "name": "solitude and PubMed",
                "members": [
                    folder_member("phases_v2/solitude"),
                    member_from_command({"pubmed_query": {"query_id": first}}),
                ],
                "archived": False,
            }
        ],
    )
    papers = [(PAPER_A, "phases_v2/solitude", "a.pdf")] + [
        (a["content_sha256"], a["storage_prefix"], a["storage_key"]) for a in pubmed[:1]
    ]
    rows.write_rows(
        "papers",
        [
            {
                "paper_id": paper_id,
                "storage_prefix": prefix,
                "storage_key": key,
                "file_name": key,
                "content_sha256": paper_id,
                "text_key": f"{paper_id}.md",
            }
            for paper_id, prefix, key in papers
        ],
    )
    chunks = [
        {"chunk_id": "a-0", "paper_id": PAPER_A, "chunker_id": CHUNKER},
        {"chunk_id": "a-1", "paper_id": PAPER_A, "chunker_id": CHUNKER},
        {"chunk_id": "p1-0", "paper_id": papers[1][0], "chunker_id": CHUNKER},
        {"chunk_id": "a-other", "paper_id": PAPER_A, "chunker_id": "another"},
    ]
    rows.write_rows("chunks", [dict(c, seq=0, text="t") for c in chunks])
    prompts = {
        WHAT.prompt_id: (WHAT.name, WHAT.output_key),
        REL.prompt_id: (REL.name, REL.output_key),
        "logical_sentences_old": ("logical_sentences", "logical_sentences"),
    }
    rows.write_rows(
        "prompts",
        [
            {
                "prompt_id": p,
                "name": name,
                "output_key": key,
                "template": "{chunk_text}",
            }
            for p, (name, key) in prompts.items()
        ],
    )
    extractions = [
        _extraction("a-0", WHAT),
        _extraction("a-0", REL),
        _extraction(
            "a-1",
            WHAT,
            "failed",
            None,
            "extraction tool call failed: Connection error.",
        ),
        _extraction(
            "a-1",
            REL,
            "failed",
            '{"relations": []}',
            "extraction tool call failed: invalid RelationsOutput",
        ),
        _extraction("p1-0", WHAT, "failed", "  ", "timed out"),
        # An earlier invalid answer kept, but the last call failed at the provider.
        _extraction(
            "p1-0",
            REL,
            "failed",
            '{"relations": [{"direction": "alters"}]}',
            PROVIDER_FAILURE + "extraction tool call failed: Connection error.",
        ),
        dict(
            _extraction("a-0", WHAT),
            prompt_id="logical_sentences_old",
            extraction_id="old",
        ),
    ]
    rows.write_rows("extractions", extractions)
    items = [
        {
            "item_id": "i-what",
            "extraction_id": extractions[0]["extraction_id"],
            "prompt_id": WHAT.prompt_id,
            "chunk_id": "a-0",
            "paper_id": PAPER_A,
            "text": "Solitude helps.",
        },
        {
            "item_id": "i-rel",
            "extraction_id": extractions[1]["extraction_id"],
            "prompt_id": REL.prompt_id,
            "chunk_id": "a-0",
            "paper_id": PAPER_A,
            "text": '{"direction": "alters"}',
        },
        {
            "item_id": "i-old",
            "extraction_id": "old",
            "prompt_id": "logical_sentences_old",
            "chunk_id": "a-0",
            "paper_id": PAPER_A,
            "text": "If so, then so.",
        },
    ]
    rows.write_rows("extracted_items", items)
    projected = {("graph", "old"), ("vector_items", "i-what"), ("vector_chunks", "a-0")}
    rows.write_rows(
        "projections", [{"target": t, "key": k} for t, k in sorted(projected)]
    )
    requests = [
        {"request_id": "r-ok", "status": "succeeded", "model_id": GPT},
        {"request_id": "r-bad", "status": "failed", "model_id": GPT, "error": "exited"},
    ]
    rows.write_rows("run_requests", requests)

    snapshot = rows.snapshot()
    reader = DatasetCoverageReader(
        rows.at_snapshot(snapshot),
        snapshot=snapshot,
        pubmed=PubmedCatalog(PinnedDataset(dataset, snapshot)),
        storage=storage,
        supported=lambda name: name.endswith(".pdf"),
    )
    fake = FakeCoverageReader(
        chunks=chunks,
        prompts=prompts,
        extractions=extractions,
        items=items,
        projected=projected,
        requests=requests,
    )
    return {
        "dataset": dataset,
        "rows": rows,
        "storage": storage,
        "reader": reader,
        "fake": fake,
        "queries": (first, second),
        "paper_b": paper_b,
        "pubmed": pubmed,
    }


def _report(reader):
    return build_report(reader, SELECTION, declared=(WHAT, REL), current=(WHAT, REL))


def test_counts_agree_with_the_fake(env):
    reader, fake = env["reader"], env["fake"]
    scopes = {"all": [PAPER_A, env["pubmed"][0]["content_sha256"]], "a": [PAPER_A]}

    assert set(reader.coverage(scopes, SELECTION)) == set(
        fake.coverage(scopes, SELECTION)
    )
    assert set(reader.failures()) == set(fake.failures())
    assert set(reader.projection_backlog(SELECTION)) == set(
        fake.projection_backlog(SELECTION)
    )
    assert set(reader.prompt_versions()) == set(fake.prompt_versions())
    fake.rejected_relations = {
        "i-rel": "must be in list [increases, decreases, no-effect]"
    }
    real, faked = reader.relation_check(SELECTION), fake.relation_check(SELECTION)
    assert (real.examined, real.rejected, real.rejected_selected) == (
        faked.examined,
        faked.rejected,
        faked.rejected_selected,
    )
    assert "must be in list" in real.sample_errors["i-rel"]


def test_reads_every_source(env):
    report = _report(env["reader"])
    first, second = env["queries"]

    collections = {s.ids[0]: s for s in report.sources if s.kind == COLLECTION}
    assert set(collections) == {"gero", "mixed"}
    gero, mixed = collections["gero"], collections["mixed"]
    assert [d.path for d in gero.not_ingested] == ["phases_v2/gerotranscendence/g.pdf"]
    # a.pdf, the folder copy of PubMed paper 2 and both PubMed PDFs: the copy and
    # PubMed's own file are one paper.
    assert len(mixed.documents) == 3
    assert mixed.unsupported == 1
    assert [d.paper_id for d in mixed.not_ingested] == [env["paper_b"]]

    [search] = [s for s in report.sources if s.kind == PUBMED_SEARCH]
    assert search.ids == sorted([first, second])
    assert len(search.documents) == 2

    everything = next(s for s in report.sources if s.kind == EVERYTHING)
    assert len(everything.documents) == 4
    assert len(everything.not_ingested) == 2

    a = next(c for c in mixed.coverage if c.prompt_id == WHAT.prompt_id)
    assert (a.chunks, a.succeeded, a.not_run) == (3, 1, 0)
    assert a.failed_calls == {
        "extraction tool call failed: Connection error.": 1,
        "timed out": 1,
    }
    rel = next(c for c in mixed.coverage if c.prompt_id == REL.prompt_id)
    assert rel.failed_calls == {
        PROVIDER_FAILURE + "extraction tool call failed: Connection error.": 1
    }
    assert rel.invalid_answers == {
        "extraction tool call failed: invalid RelationsOutput": 1
    }
    assert any(
        "probabilistic_processes × openai/gpt-4.1-mini: 1 failed calls" in p
        for p in report.problems()
        if p.startswith("collection solitude and PubMed")
    )
    assert report.undeclared_prompts == ["logical_sentences"]
    assert [r["request_id"] for r in report.unfinished_requests] == ["r-bad"]
    relations = next(b for b in report.backlog if b.target == RELATIONS)
    assert (relations.outstanding, relations.selected) == (1, 1)
    # "alters" is not a direction the relation contract accepts.
    check = report.relation_check
    assert (check.examined, check.rejected, check.rejected_selected) == (1, 1, 1)
    assert not any(RELATIONS in p for p in report.problems())


def test_reads_one_snapshot(env):
    reader, rows = env["reader"], env["rows"]
    before = reader.run_requests()

    rows.write_rows("run_requests", [{"request_id": "r-late", "status": "succeeded"}])

    assert reader.run_requests() == before
    assert len(rows.query("SELECT * FROM run_requests")) == len(before) + 1


def test_writes_nothing(env):
    dataset, storage = env["dataset"], env["storage"]
    snapshots = len(dataset.list_snapshots())
    files = dict(storage.files)

    _report(env["reader"])

    assert len(dataset.list_snapshots()) == snapshots
    assert storage.files == files
