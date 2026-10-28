"""The assistant's tools, called as the assistant calls them, on real datasets.

The application services are the real ones the endpoints use, over a DuckLake
store; only what reaches outside is faked: NCBI, the request queue, the model
a try calls and the search index. Each tool is shown working and refusing.
"""

import inspect
import json
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace

import pytest
from naas_abi_core.services.dataset.adapters.secondary.DatasetSecondaryAdapterDuckLake import (
    DatasetSecondaryAdapterDuckLake,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService

from openalex.adapters.secondary.openalex_dataset_store import OpenalexDatasetStore
from openalex.adapters.secondary.openalex_pubmed_catalog import (
    PubmedCatalog as OpenalexCatalog,
)
from openalex.application.openalex_service import OpenalexService
from phases_v2 import identity
from phases_v2.app.app_resources_test import PdfOnly, Storage
from phases_v2.app.service import PipelineAppService
from phases_v2.assistant import tools as tools_module
from phases_v2.assistant import workspace as workspace_module
from phases_v2.assistant.confirmations import (
    ConfirmationGuard,
    ConfirmationRefused,
    RequestContext,
)
from phases_v2.assistant.tools import COSTLY_PAIRS, build_tools
from phases_v2.assistant.workspace import Unavailable, WorkspaceActions
from phases_v2.chunking.chunkers import WINDOW_512_128
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.datasets.schemas import DATASETS
from phases_v2.datasets.store import ensure_datasets
from phases_v2.extraction.fakes import FakeModel
from phases_v2.models.catalog import DECLARED_MODELS
from phases_v2.paper_collections.adapters.secondary.StoredMemberSources import (
    StoredMemberSources,
)
from phases_v2.prompts.domain import PromptTemplate
from phases_v2.requests.fakes import FakeRequestStore
from phases_v2.search.models import SearchHit
from phases_v2.sources.adapters.secondary.phases_v2_pubmed_catalog import PubmedCatalog
from pubmed.adapters.secondary.pubmed_dataset_store import PubmedDatasetStore
from pubmed.application.pubmed_service import PubmedService
from pubmed.tests.pubmed_service_test import FakeSource, queue

CHUNKER = WINDOW_512_128.chunker_id
MODEL = DECLARED_MODELS[0].model_id
CLAIMS = PromptTemplate("Claims", "List the claims in {chunk_text}", "results")
PDF = b"%PDF-1.7 loneliness and sleep"
PAPER = sha256(PDF).hexdigest()
EARLIER_RUN = "11111111-1111-1111-1111-111111111111"


class FakeSearch:
    """The search service's reading side, recording what it was asked."""

    def __init__(self):
        self.calls = []

    def read_view(self, snapshot):
        return self, 7

    def page(self, mode, query, limit, offset, **options):
        self.calls.append({**options, "mode": mode, "query": query, "limit": limit})
        hit = SearchHit(
            item_id="item-1",
            extracted_text="Time alone lowers stress.",
            score=0.91,
            prompt_name="Claims",
            model_id=MODEL,
            chunk_seq=0,
            paper_id=PAPER,
            paper_name="loneliness.pdf",
        )
        return [hit], 1


def _seed(rows, storage):
    storage.put_object("phases_v2/studies", "loneliness.pdf", PDF)
    rows.write_rows(
        "papers",
        [
            {
                "paper_id": PAPER,
                "storage_prefix": "phases_v2/studies",
                "storage_key": "loneliness.pdf",
                "file_name": "loneliness.pdf",
                "content_sha256": PAPER,
                "text_key": f"{PAPER}.md",
            }
        ],
    )
    rows.write_rows(
        "chunks",
        [
            {
                "chunk_id": identity.chunk_id(PAPER, CHUNKER, seq),
                "paper_id": PAPER,
                "chunker_id": CHUNKER,
                "seq": seq,
                "text": f"Chunk {seq}: people who live alone sleep less.",
            }
            for seq in range(4)
        ],
    )
    rows.write_rows(
        "prompts",
        [
            {
                "prompt_id": CLAIMS.prompt_id,
                "name": CLAIMS.name,
                "prompt_sha256": identity.prompt_sha256(CLAIMS.template),
                "template": CLAIMS.template,
                "output_key": CLAIMS.output_key,
                "registered_at": datetime(2026, 1, 1, tzinfo=UTC),
            }
        ],
    )
    extractions, items = [], []
    for seq in (0, 1):
        chunk_id = identity.chunk_id(PAPER, CHUNKER, seq)
        extraction_id = identity.extraction_id(chunk_id, MODEL, CLAIMS.prompt_id)
        extractions.append(
            {
                "extraction_id": extraction_id,
                "chunk_id": chunk_id,
                "model_id": MODEL,
                "prompt_id": CLAIMS.prompt_id,
                "run_id": f"{EARLIER_RUN}:{CLAIMS.prompt_id}",
                "status": "succeeded",
                "completed_at": datetime(2026, 2, 1, tzinfo=UTC),
            }
        )
        items.append(
            {
                "item_id": identity.item_id(extraction_id, 0),
                "extraction_id": extraction_id,
                "chunk_id": chunk_id,
                "paper_id": PAPER,
                "prompt_id": CLAIMS.prompt_id,
                "seq": 0,
                "text": f"Living alone shortens sleep ({seq}).",
            }
        )
    rows.write_rows("extractions", extractions)
    rows.write_rows("extracted_items", items)


def build_store(path):
    """A fresh store with a downloaded PubMed search and one ingested paper.

    Slow to make (every dataset is created), so tests share one per module and
    keep to their own collections, searches and requests.
    """
    dataset = DatasetService(
        adapter=DatasetSecondaryAdapterDuckLake(
            catalog=f"sqlite:{path / 'catalog.sqlite'}",
            data_path=str(path / "warehouse") + "/",
        )
    )
    store = PubmedDatasetStore(dataset)
    store.ensure()
    storage = Storage()
    publisher = PubmedService(store, FakeSource(), storage)
    downloaded = queue(publisher)
    publisher.execute(downloaded["request_id"], "run")
    OpenalexDatasetStore(dataset).ensure()
    ensure_datasets(dataset)
    rows = DatasetRowStore(dataset)
    _seed(rows, storage)
    return SimpleNamespace(
        dataset=dataset,
        rows=rows,
        storage=storage,
        publisher=publisher,
        downloaded_search=downloaded["query_id"],
    )


def build_env(store, *, search=True, pubmed=True, openalex=True, context=None):
    """The real services over ``store``, and the tools built on them.

    The request context is ``env.context``, which a test changes to play a new
    user message, unless ``context`` provides another.
    """
    requests = FakeRequestStore()
    catalog = PubmedCatalog(store.dataset)
    model = FakeModel(json.dumps({"results": ["a new claim"]}))
    pipeline = PipelineAppService(
        requests,
        object_storage=store.storage,
        rows=store.rows,
        pubmed_catalog=catalog,
        collection_sources=StoredMemberSources(store.rows, store.storage, catalog),
        renderer=PdfOnly(),
        model_factory=lambda model_id, output_key: model,
    )
    enricher = OpenalexService(
        OpenalexDatasetStore(store.dataset), OpenalexCatalog(store.dataset), source=None
    )
    asking = {"conversation": "chat-1", "user": "jeremy@naas.ai", "turn": "t1"}
    found = FakeSearch()
    actions = WorkspaceActions(
        pipeline,
        guard=ConfirmationGuard(),
        context=context or (lambda: RequestContext(**asking)),
        search=(lambda: found) if search else None,
        pubmed=store.publisher if pubmed else None,
        openalex=enricher if openalex else None,
    )
    return SimpleNamespace(
        tools={t.name: t for t in build_tools(actions)},
        actions=actions,
        context=asking,
        pipeline=pipeline,
        rows=store.rows,
        requests=requests,
        publisher=store.publisher,
        enricher=enricher,
        search=found,
        model=model,
        downloaded_search=store.downloaded_search,
    )


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    return build_store(tmp_path_factory.mktemp("assistant"))


@pytest.fixture
def env(store):
    return build_env(store)


def call(env, tool, **args):
    return env.tools[tool].invoke(args)


def user_says(env, turn):
    """The user writes again: what follows answers their new message."""
    env.context["turn"] = turn


def run_choices(collection_id):
    return {
        "collection_id": collection_id,
        "chunker_id": CHUNKER,
        "prompt_ids": [CLAIMS.prompt_id],
        "model_id": MODEL,
    }


def collection_with_the_paper(env, name="Sleep"):
    return call(env, "create_collection", name=name, paper_ids=[PAPER])


# -- what the assistant has, and what it does not ------------------------------


def test_there_is_no_tool_that_deletes_archives_removes_or_disables(env):
    forbidden = ("delete", "archive", "remove", "disable", "toggle", "discard")
    assert not [n for n in env.tools if any(word in n for word in forbidden)]
    # Nor does any tool reach a service call that does.
    for module in (workspace_module, tools_module):
        source = inspect.getsource(module)
        for call_name in (
            "archive_collection",
            "remove_member",
            "schedules.toggle",
            ".toggle(",
            ".delete(",
            "resume",
            "retry",
        ):
            assert call_name not in source, (module.__name__, call_name)


def test_every_costly_action_is_a_prepare_and_execute_pair(env):
    for prepare, execute in COSTLY_PAIRS.items():
        assert prepare in env.tools and execute in env.tools
        schema = env.tools[execute].tool_call_schema.model_json_schema()
        assert "confirmation_token" in schema["required"], execute
        prepared = set(
            env.tools[prepare].tool_call_schema.model_json_schema()["properties"]
        )
        assert set(schema["properties"]) == prepared | {"confirmation_token"}


# -- collections ---------------------------------------------------------------


def test_a_collection_is_created_from_a_pubmed_search_and_papers_are_added(env):
    found = call(env, "search_pubmed", query="solitude sleep", max_results=20)
    assert found["matches_in_pubmed"] == 2
    assert [p["pmid"] for p in found["papers"]] == ["1", "2"]

    created = call(
        env,
        "create_collection",
        name="Solitude studies",
        description="Being alone and health",
        pubmed_search_ids=[found["search_id"]],
    )
    assert created["name"] == "Solitude studies"
    assert created["papers_total"] == 2
    assert created["where"] == "Collections → Solitude studies"
    assert created["members"][0]["kind"] == "pubmed_query"

    added = call(
        env,
        "add_to_collection",
        collection_id=created["collection_id"],
        paper_ids=[PAPER],
    )
    assert added["papers_total"] == 3
    assert {p["paper_id"]: p["status"] for p in added["papers"]}[PAPER] == "results"

    again = call(
        env,
        "add_to_collection",
        collection_id=created["collection_id"],
        paper_ids=[PAPER],
    )
    assert len(again["members"]) == 2, "adding a member twice changes nothing"

    listed = call(env, "list_collections")["collections"]
    assert ("Solitude studies", 3) in [(c["name"], c["papers"]) for c in listed]


def test_renaming_keeps_what_is_not_given(env):
    created = call(env, "create_collection", name="Draft", description="Keep me")

    renamed = call(
        env, "update_collection", collection_id=created["collection_id"], name="Final"
    )

    assert (renamed["name"], renamed["description"]) == ("Final", "Keep me")
    described = call(
        env,
        "update_collection",
        collection_id=created["collection_id"],
        description="New words",
    )
    assert (described["name"], described["description"]) == ("Final", "New words")


def test_collection_refusals_are_plain(env):
    with pytest.raises(LookupError, match="Collection not found"):
        call(
            env, "get_collection", collection_id="00000000-0000-0000-0000-000000000000"
        )
    with pytest.raises(ValueError, match="name"):
        call(env, "create_collection", name="   ")
    created = call(env, "create_collection", name="Empty")
    with pytest.raises(ValueError, match="Name at least one thing to add"):
        call(env, "add_to_collection", collection_id=created["collection_id"])
    with pytest.raises(ValueError):
        call(
            env,
            "add_to_collection",
            collection_id=created["collection_id"],
            pubmed_search_ids=["not-a-uuid"],
        )


# -- PubMed --------------------------------------------------------------------


def test_saved_searches_and_the_library_can_be_read(env):
    searches = call(env, "list_pubmed_searches")["searches"]
    downloaded = {s["search_id"]: s for s in searches}[env.downloaded_search]
    assert downloaded["downloaded_papers"] == 2

    one = call(env, "get_pubmed_search", search_id=env.downloaded_search)
    assert (one["previewed"], one["downloaded"]) == (2, 2)

    library = call(env, "browse_library")
    assert library["total"] == 2
    assert all(p["downloaded"] for p in library["papers"])
    assert call(env, "browse_library", search="Paper 2")["total"] == 1


def test_pubmed_refusals_are_plain(env, store):
    missing = "00000000-0000-4000-8000-000000000000"
    with pytest.raises(LookupError, match=f"Nothing was found with the id {missing}"):
        call(env, "get_pubmed_search", search_id=missing)
    with pytest.raises(ValueError):
        call(env, "search_pubmed", query="   ")
    without = build_env(store, pubmed=False, openalex=False)
    with pytest.raises(Unavailable, match="PubMed is unavailable"):
        call(without, "search_pubmed", query="solitude")
    with pytest.raises(Unavailable, match="OpenAlex enrichment is unavailable"):
        call(without, "prepare_openalex_enrichment", search_id=missing)


# -- prompts, models, trying ---------------------------------------------------


def test_prompts_versions_models_and_chunkers_can_be_read(env):
    prompts = call(env, "list_prompts")["prompts"]
    assert CLAIMS.prompt_id in {p["prompt_id"] for p in prompts}

    versions = call(env, "get_prompt_versions", name="Claims")
    assert CLAIMS.template in [v["template"] for v in versions["versions"]]
    assert versions["where"] == "Prompts → Claims → Versions"

    choices = call(env, "list_models_and_chunkers")
    assert MODEL in {m["model_id"] for m in choices["models"]}
    assert CHUNKER in {c["chunker_id"] for c in choices["chunkers"]}

    with pytest.raises(LookupError, match="No prompt is named"):
        call(env, "get_prompt_versions", name="Nothing")


def test_a_version_is_saved_once(env):
    text = "List the claims and their evidence in {chunk_text}"

    saved = call(env, "save_prompt_version", name="Claims", template=text)
    again = call(env, "save_prompt_version", name="Claims", template=text)

    assert saved["prompt_id"] == again["prompt_id"] != CLAIMS.prompt_id
    assert (saved["already_saved"], again["already_saved"]) == (False, True)
    versions = call(env, "get_prompt_versions", name="Claims")["versions"]
    assert [v["prompt_id"] for v in versions] == [saved["prompt_id"], CLAIMS.prompt_id]
    with pytest.raises(ValueError):
        call(env, "save_prompt_version", name="Claims", template="No placeholder")


def _dataset_counts(rows):
    return {
        spec.name: rows.query(f"SELECT count(*) AS n FROM {spec.name}")[0]["n"]  # nosec B608
        for spec in DATASETS
    }


def test_trying_a_draft_reports_each_chunk_next_to_the_earlier_version(env):
    before = _dataset_counts(env.rows)

    tried = call(
        env,
        "try_prompt",
        paper_id=PAPER,
        model_id=MODEL,
        chunker_id=CHUNKER,
        name="Claims",
        template="Claims with numbers in {chunk_text}",
        output_format="results",
        chunk_seqs=[0, 2],
        compare_with_prompt_id=CLAIMS.prompt_id,
    )

    assert [c["seq"] for c in tried["chunks"]] == [0, 2]
    assert tried["chunks"][0]["items"] == ["a new claim"]
    assert tried["chunks"][0]["earlier"]["items"] == [
        "Living alone shortens sleep (0)."
    ]
    assert tried["chunks"][1]["earlier"]["status"] == "not_run"
    assert tried["saved"] is False
    assert _dataset_counts(env.rows) == before, "trying writes nothing"


def test_trying_a_saved_version_takes_the_first_chunks(env):
    tried = call(
        env,
        "try_prompt",
        paper_id=PAPER,
        model_id=MODEL,
        chunker_id=CHUNKER,
        prompt_id=CLAIMS.prompt_id,
        first=2,
    )

    assert [c["seq"] for c in tried["chunks"]] == [0, 1]
    assert "List the claims in Chunk 0" in env.model.prompts[0]


@pytest.mark.parametrize(
    "change, refusal",
    [
        ({"chunk_seqs": list(range(11))}, "at most 10 chunks"),
        ({"template": "no placeholder"}, "must contain {chunk_text}"),
        ({"prompt_id": CLAIMS.prompt_id}, "one thing at a time"),
        ({"template": "", "prompt_id": ""}, "Give a saved prompt version"),
        ({"chunker_id": "window_9_zzz"}, "not chunked|chunker"),
    ],
)
def test_trying_refuses_in_plain_words(env, change, refusal):
    args = {
        "paper_id": PAPER,
        "model_id": MODEL,
        "chunker_id": CHUNKER,
        "template": "Try {chunk_text}",
    }
    args.update(change)
    with pytest.raises(ValueError, match=refusal):
        call(env, "try_prompt", **args)


# -- papers, results, search ---------------------------------------------------


def test_papers_and_one_papers_results_can_be_read(env):
    papers = call(env, "list_papers", has_results=True)
    assert [p["paper_id"] for p in papers["papers"]] == [PAPER]
    assert papers["papers"][0]["results"] == 2

    results = call(env, "get_paper_results", paper_id=PAPER)
    assert results["title"] == "loneliness.pdf"
    [group] = results["results"]
    assert (group["prompt_name"], group["model_id"], group["item_count"]) == (
        "Claims",
        MODEL,
        2,
    )
    assert [i["text"] for i in group["items"]] == [
        "Living alone shortens sleep (0).",
        "Living alone shortens sleep (1).",
    ]
    assert results["ran"][0]["request_ids"] == [EARLIER_RUN]
    narrowed = call(env, "get_paper_results", paper_id=PAPER, model_id="other/model")
    assert narrowed["results"] == []

    chunks = call(env, "get_paper_chunks", paper_id=PAPER, chunker_id=CHUNKER)
    assert [c["seq"] for c in chunks["chunks"]] == [0, 1, 2, 3]

    with pytest.raises(LookupError):
        call(env, "get_paper_results", paper_id="f" * 64)


def test_search_finds_findings_within_a_collection(env):
    created = collection_with_the_paper(env)

    found = call(
        env,
        "search_findings",
        query="being alone",
        by="keyword",
        collection_id=created["collection_id"],
    )

    assert found["hits"][0]["finding"] == "Time alone lowers stress."
    assert found["hits"][0]["paper_id"] == PAPER
    assert env.search.calls[-1]["papers"] == [PAPER]
    assert env.search.calls[-1]["mode"] == "keyword"
    call(env, "search_findings", query="being alone")
    assert "papers" not in env.search.calls[-1]
    assert env.search.calls[-1]["mode"] == "semantic"


def test_search_refusals_are_plain(env, store):
    with pytest.raises(ValueError, match="by 'meaning' or by 'keyword'"):
        call(env, "search_findings", query="x", by="effects")
    without = build_env(store, search=False)
    with pytest.raises(Unavailable, match="Search is unavailable"):
        call(without, "search_findings", query="x")


# -- runs and configurations ---------------------------------------------------


def test_a_configuration_is_saved_without_queuing_anything(env):
    created = collection_with_the_paper(env)

    saved = call(
        env,
        "save_run_configuration",
        name="Sleep claims",
        **run_choices(created["collection_id"]),
    )

    assert saved["queued"] is False
    listed = call(env, "list_run_configurations")["configurations"]
    assert saved["configuration_id"] in [c["configuration_id"] for c in listed]
    assert env.requests.requests == {}
    with pytest.raises(ValueError, match="model_id"):
        call(
            env,
            "save_run_configuration",
            name="Broken",
            **dict(run_choices(created["collection_id"]), model_id="nobody/none"),
        )


def test_a_run_is_queued_only_after_a_yes_and_records_who_asked(env):
    collection = collection_with_the_paper(env, "Sleep")
    choices = run_choices(collection["collection_id"])

    prepared = call(env, "prepare_run", **choices)

    assert "collection “Sleep”: 1 paper (1 already with results" in prepared["summary"]
    assert "Claims (version" in prepared["summary"]
    assert MODEL in prepared["summary"]
    assert prepared["papers"] == 1
    assert env.requests.requests == {}, "preparing queues nothing"

    token = prepared["confirmation_token"]
    with pytest.raises(ConfirmationRefused, match="has not answered yet"):
        call(env, "queue_run", confirmation_token=token, **choices)
    assert env.requests.requests == {}

    user_says(env, "t2")
    queued = call(env, "queue_run", confirmation_token=token, **choices)

    request = env.requests.requests[queued["run_id"]]
    assert request.requested_by == "jeremy@naas.ai"
    assert request.prompt_ids == [CLAIMS.prompt_id]
    assert queued["where"] == f"Runs → {queued['run_id']}"

    run = call(env, "get_run", run_id=queued["run_id"])
    assert (run["status"], run["collection"]) == ("pending", "Sleep")
    assert call(env, "list_runs")["runs"][0]["run_id"] == queued["run_id"]

    with pytest.raises(ConfirmationRefused, match="already used"):
        call(env, "queue_run", confirmation_token=token, **choices)
    assert len(env.requests.requests) == 1


@pytest.mark.parametrize(
    "token, change, refusal",
    [
        ("", {}, "No confirmation token"),
        ("made-up", {}, "not one this assistant issued"),
        (
            None,
            {"model_id": DECLARED_MODELS[1].model_id},
            "different action or different",
        ),
        (None, {"prompt_ids": []}, "different action or different"),
    ],
)
def test_a_run_without_a_valid_matching_token_is_refused(env, token, change, refusal):
    collection = collection_with_the_paper(env)
    choices = run_choices(collection["collection_id"])
    prepared = call(env, "prepare_run", **choices)
    user_says(env, "t2")

    with pytest.raises(ConfirmationRefused, match=refusal):
        call(
            env,
            "queue_run",
            confirmation_token=prepared["confirmation_token"]
            if token is None
            else token,
            **dict(choices, **change),
        )
    assert env.requests.requests == {}


def test_a_token_from_another_conversation_is_refused(env):
    choices = run_choices(collection_with_the_paper(env)["collection_id"])
    token = call(env, "prepare_run", **choices)["confirmation_token"]
    env.context.update(conversation="chat-2", turn="t2")

    with pytest.raises(ConfirmationRefused, match="another conversation"):
        call(env, "queue_run", confirmation_token=token, **choices)
    assert env.requests.requests == {}


def test_an_expired_token_is_refused(env):
    clock = {"now": 0.0}
    env.actions._guard = ConfirmationGuard(clock=lambda: clock["now"])
    choices = run_choices(collection_with_the_paper(env)["collection_id"])
    token = call(env, "prepare_run", **choices)["confirmation_token"]
    user_says(env, "t2")
    clock["now"] = 601.0

    with pytest.raises(ConfirmationRefused, match="expired"):
        call(env, "queue_run", confirmation_token=token, **choices)
    assert env.requests.requests == {}


def test_a_collection_that_changed_after_the_yes_was_asked_needs_a_new_one(env):
    collection = collection_with_the_paper(env)
    choices = run_choices(collection["collection_id"])
    token = call(env, "prepare_run", **choices)["confirmation_token"]
    call(
        env, "add_to_collection", collection_id=collection["collection_id"], pmids=["1"]
    )
    user_says(env, "t2")

    with pytest.raises(ConfirmationRefused, match="changed after it was prepared"):
        call(env, "queue_run", confirmation_token=token, **choices)
    assert env.requests.requests == {}


def test_a_run_that_would_be_refused_is_not_offered(env):
    empty = call(env, "create_collection", name="Empty")
    with pytest.raises(ValueError, match="no papers yet"):
        call(env, "prepare_run", **run_choices(empty["collection_id"]))
    full = collection_with_the_paper(env)
    with pytest.raises(ValueError, match="model_id"):
        call(
            env,
            "prepare_run",
            **dict(run_choices(full["collection_id"]), model_id="nobody/none"),
        )
    with pytest.raises(ValueError, match="prompt"):
        call(
            env,
            "prepare_run",
            **dict(run_choices(full["collection_id"]), prompt_ids=["unknown"]),
        )
    with pytest.raises(LookupError):
        call(env, "get_run", run_id="unknown-run")


# -- PubMed downloads, schedules, OpenAlex -------------------------------------


def test_previewed_papers_are_downloaded_only_after_a_yes(env):
    search = call(env, "search_pubmed", query="solitude")["search_id"]
    before = len(env.publisher.requests())

    prepared = call(env, "prepare_pubmed_ingestion", search_id=search, pmids=["2"])

    assert prepared["summary"].startswith("Download the full text of 1 paper")
    assert "downloaded before" in prepared["summary"]
    assert len(env.publisher.requests()) == before
    user_says(env, "t2")
    queued = call(
        env,
        "queue_pubmed_ingestion",
        confirmation_token=prepared["confirmation_token"],
        search_id=search,
        pmids=["2"],
    )
    assert queued["papers"] == 1
    assert len(env.publisher.requests()) == before + 1
    assert (
        call(env, "list_downloads_and_enrichments")["downloads"][0]["request_id"]
        == (queued["download_id"])
    )

    with pytest.raises(ValueError, match="not among the search's previewed papers"):
        call(env, "prepare_pubmed_ingestion", search_id=search, pmids=["99"])


def test_downloading_everything_a_search_matches_is_a_full_ingestion(env):
    search = call(env, "search_pubmed", query="solitude")["search_id"]
    prepared = call(env, "prepare_pubmed_ingestion", search_id=search, which="all")
    assert "every paper PubMed matches" in prepared["summary"]

    with pytest.raises(ConfirmationRefused, match="different action or different"):
        user_says(env, "t2")
        call(
            env,
            "queue_pubmed_ingestion",
            confirmation_token=prepared["confirmation_token"],
            search_id=search,
            which="previewed",
        )
    queued = call(
        env,
        "queue_pubmed_ingestion",
        confirmation_token=prepared["confirmation_token"],
        search_id=search,
        which="all",
    )
    assert queued["full_ingestion_id"]
    listed = call(env, "list_downloads_and_enrichments")["full_ingestions"]
    assert queued["full_ingestion_id"] in [b["backfill_id"] for b in listed]
    with pytest.raises(ValueError, match="which must be"):
        call(env, "prepare_pubmed_ingestion", search_id=search, which="some")


def test_a_schedule_is_created_only_after_a_yes(env):
    search = call(env, "search_pubmed", query="solitude")["search_id"]

    prepared = call(
        env,
        "prepare_pubmed_schedule",
        search_id=search,
        name="Weekly solitude",
        interval_hours=168,
    )

    assert "every week, and download the new papers" in prepared["summary"]
    schedules = call(env, "list_downloads_and_enrichments")["schedules"]
    user_says(env, "t2")
    created = call(
        env,
        "create_pubmed_schedule",
        confirmation_token=prepared["confirmation_token"],
        search_id=search,
        name="Weekly solitude",
        interval_hours=168,
    )
    after = call(env, "list_downloads_and_enrichments")["schedules"]
    assert len(after) == len(schedules) + 1
    schedule = {s["schedule_id"]: s for s in after}[created["schedule_id"]]
    assert (schedule["how_often"], schedule["enabled"]) == ("every week", True)
    with pytest.raises(ValueError, match="interval_hours"):
        call(
            env, "prepare_pubmed_schedule", search_id=search, name="x", interval_hours=2
        )


def test_openalex_enrichment_is_queued_only_after_a_yes(env):
    prepared = call(env, "prepare_openalex_enrichment", search_id=env.downloaded_search)

    assert prepared["summary"].startswith("Enrich 2 papers of the saved PubMed search")
    before = len(env.enricher.requests())
    with pytest.raises(ConfirmationRefused, match="has not answered yet"):
        call(
            env,
            "queue_openalex_enrichment",
            confirmation_token=prepared["confirmation_token"],
            search_id=env.downloaded_search,
        )
    user_says(env, "t2")
    queued = call(
        env,
        "queue_openalex_enrichment",
        confirmation_token=prepared["confirmation_token"],
        search_id=env.downloaded_search,
    )
    assert queued["papers"] == 2
    assert len(env.enricher.requests()) == before + 1
    assert env.enricher.requests()[0]["request_id"] == queued["enrichment_id"]
    with pytest.raises(LookupError):
        call(
            env,
            "prepare_openalex_enrichment",
            search_id="00000000-0000-4000-8000-000000000000",
        )
