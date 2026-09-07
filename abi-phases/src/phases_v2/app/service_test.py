"""What the app offers a user, without a web server in the way."""

import pytest

from phases_v2.app.service import PipelineAppService
from phases_v2.models.catalog import DECLARED_MODELS
from phases_v2.chunking.chunkers import WINDOW_512_128
from phases_v2.requests.fakes import FakeRequestStore
from phases_v2.requests.interfaces import PENDING


class _Rows:
    def __init__(self, results=None):
        self._results = results or {}

    def query(self, sql):
        for marker, rows in self._results.items():
            if marker in sql:
                return rows
        return []


class _Storage:
    def __init__(self, keys=None, raises=False, tree=None):
        self._keys = keys or []
        self._raises = raises
        self._tree = tree or {}

    def list_objects(self, prefix):
        if self._raises:
            raise RuntimeError("no such prefix")
        return list(self._keys)

    def list_objects_recursive(self, prefix):
        if prefix not in self._tree:
            raise RuntimeError(f"{prefix} not found")
        return list(self._tree[prefix])


def _service(**kwargs):
    kwargs.setdefault("request_store", FakeRequestStore())
    return PipelineAppService(**kwargs)


def test_the_offered_prompts_models_and_chunkers_are_the_declared_ones():
    service = _service()

    assert service.prompts()
    assert service.models()
    assert {c["chunker_id"] for c in service.chunkers()} == {
        WINDOW_512_128.chunker_id
    }
    assert all("prompt_id" in p for p in service.prompts())
    assert all("model_id" in m for m in service.models())


def test_locations_are_scoped_to_the_modules_own_prefix():
    # The storage root is shared with every other module; offering their
    # prefixes as a paper source is how you ingest someone else's telemetry.
    service = _service(
        object_storage=_Storage(["phases_v2/solitude", "phases_v2/gero"]),
        papers_root="phases_v2",
    )

    prefixes = [loc["prefix"] for loc in service.locations()]

    assert prefixes == ["phases_v2", "phases_v2/gero", "phases_v2/solitude"]
    assert all(p.startswith("phases_v2") for p in prefixes)


def test_the_root_itself_is_always_offered():
    # So dropping PDFs straight into it works.
    service = _service(object_storage=_Storage([]), papers_root="phases_v2")

    assert service.locations()[0]["prefix"] == "phases_v2"


def test_a_root_that_does_not_exist_yet_still_shows_itself():
    service = _service(object_storage=_Storage(raises=True), papers_root="phases_v2")

    assert [loc["prefix"] for loc in service.locations()] == ["phases_v2"]


def test_the_root_is_configurable():
    service = _service(
        object_storage=_Storage(["corpora/a"]), papers_root="corpora"
    )

    assert [loc["prefix"] for loc in service.locations()] == ["corpora", "corpora/a"]


def test_another_modules_prefix_is_never_offered():
    # `naas_abi` sits beside us in the storage root and holds its own data.
    service = _service(
        object_storage=_Storage(["phases_v2/papers"]), papers_root="phases_v2"
    )

    assert not any("naas_abi" in loc["prefix"] for loc in service.locations())


def test_submitting_records_a_pending_request():
    store = FakeRequestStore()
    service = _service(request_store=store)

    request = service.submit_run(
        locations=["papers"],
        chunker_id="w",
        prompt_ids=["p"],
        model_id="m",
        requested_by="maxime",
    )

    assert request.status == PENDING
    assert store.get(request.request_id).requested_by == "maxime"


def test_submitting_without_a_required_input_is_refused_and_names_it():
    service = _service()

    with pytest.raises(ValueError, match="model_id"):
        service.submit_run(
            locations=["papers"], chunker_id="w", prompt_ids=["p"], model_id=""
        )


def test_submitting_with_no_location_is_refused():
    service = _service()

    with pytest.raises(ValueError, match="locations"):
        service.submit_run(
            locations=[], chunker_id="w", prompt_ids=["p"], model_id="m"
        )


def test_a_completed_request_sums_the_counts_across_its_prompts():
    # One request runs several prompts, each its own extraction run; the user
    # asked for one run, so they should see one set of totals.
    store = FakeRequestStore()
    service = _service(
        request_store=store,
        rows=_Rows({"extraction_runs": [
            {"succeeded": 7, "failed": 1, "skipped": 2},
            {"succeeded": 3, "failed": 0, "skipped": 5},
        ]}),
    )
    request = service.submit_run(
        locations=["papers"], chunker_id="w", prompt_ids=["p1", "p2"], model_id="m"
    )

    counts = service.request(request.request_id)["counts"]

    assert counts["succeeded"] == 10
    assert counts["failed"] == 1
    assert counts["skipped"] == 7
    assert counts["prompts_run"] == 2


def test_a_request_with_no_run_yet_reports_no_counts():
    store = FakeRequestStore()
    service = _service(request_store=store, rows=_Rows())
    request = service.submit_run(
        locations=["papers"], chunker_id="w", prompt_ids=["p"], model_id="m"
    )

    assert service.request(request.request_id)["counts"] is None


def test_choosing_a_different_chunker_warns_that_everything_re_runs():
    service = _service(rows=_Rows({"DISTINCT chunker_id": [{"chunker_id": "window_1_aaa"}]}))

    warning = service.chunker_warning("window_1_bbb")

    assert warning is not None
    assert "window_1_aaa" in warning
    assert "outstanding" in warning


def test_choosing_the_chunker_already_in_use_warns_about_nothing():
    service = _service(rows=_Rows({"DISTINCT chunker_id": [{"chunker_id": "window_1_aaa"}]}))

    assert service.chunker_warning("window_1_aaa") is None


def test_an_empty_corpus_warns_about_nothing():
    service = _service(rows=_Rows({"DISTINCT chunker_id": []}))

    assert service.chunker_warning("window_1_aaa") is None


def test_models_are_marked_with_whether_they_can_actually_be_built():
    # A declared model whose provider nothing registers would fail at run
    # time. The chooser must not offer it as if it were usable.
    #
    # Deliberately not naming a model: the catalog changes as routes change,
    # and this is about the marking, not about which model is reachable today.
    usable = DECLARED_MODELS[0].model_id
    service = _service(is_model_available=lambda model_id: model_id == usable)

    models = {m["model_id"]: m["available"] for m in service.models()}

    assert models[usable] is True
    assert all(
        available is False
        for model_id, available in models.items()
        if model_id != usable
    )


def test_without_a_resolver_every_model_is_assumed_available():
    service = _service()

    assert all(m["available"] for m in service.models())


def test_availability_does_not_remove_the_model_from_the_catalog():
    # Existing extractions reference it, so it stays listed and attributable —
    # it is just not offered as a choice.
    service = _service(is_model_available=lambda _id: False)

    assert len(service.models()) == len(DECLARED_MODELS)


# -- document preview ---------------------------------------------------


def _with_docs(tree, ingested=()):
    rows = _Rows({"file_name": [{"file_name": n} for n in ingested]})
    return _service(object_storage=_Storage(tree=tree), rows=rows)


def test_the_preview_lists_documents_at_every_depth():
    service = _with_docs({"papers": ["a.pdf", "2024/b.pdf", "2024/q1/c.pdf"]})

    preview = service.documents(["papers"])

    assert preview["total"] == 3
    assert [d["name"] for d in preview["documents"]] == ["b.pdf", "c.pdf", "a.pdf"]


def test_the_preview_says_which_documents_are_already_ingested():
    # This is the difference between a run that costs something and one that
    # does not, so it belongs in the preview rather than after the fact.
    service = _with_docs({"papers": ["a.pdf", "b.pdf"]}, ingested=["a.pdf"])

    preview = service.documents(["papers"])

    assert preview["already_ingested"] == 1
    by_name = {d["name"]: d["already_ingested"] for d in preview["documents"]}
    assert by_name == {"a.pdf": True, "b.pdf": False}


def test_the_preview_spans_several_locations():
    service = _with_docs({"papers": ["a.pdf"], "archive": ["b.pdf"]})

    preview = service.documents(["papers", "archive"])

    assert preview["total"] == 2
    assert {d["location"] for d in preview["documents"]} == {"papers", "archive"}


def test_an_unreachable_location_is_reported_without_losing_the_others():
    service = _with_docs({"papers": ["a.pdf"]})

    preview = service.documents(["nope", "papers"])

    assert preview["total"] == 1
    assert any("nope" in f for f in preview["failed_locations"])


def test_a_large_location_is_truncated_but_says_so():
    service = _with_docs({"papers": [f"{i}.pdf" for i in range(500)]})

    preview = service.documents(["papers"], limit=10)

    assert len(preview["documents"]) == 10
    assert preview["total"] == 500
    assert preview["truncated"] is True


def test_selecting_nothing_previews_nothing():
    service = _with_docs({"papers": ["a.pdf"]})

    assert service.documents([])["total"] == 0


class _PdfOnly:
    def handles(self, file_name):
        return file_name.lower().endswith(".pdf")


def test_the_preview_separates_papers_from_other_modules_data():
    # The object-storage root holds other modules' files. "How many objects are
    # here" is not "how many papers", and the difference should be visible
    # before a run rather than discovered from its report.
    service = PipelineAppService(
        request_store=FakeRequestStore(),
        object_storage=_Storage(
            tree={"naas_abi": ["nexus/analytics/events.json", "nexus/a/s.pkl", "x.pdf"]}
        ),
        rows=_Rows(),
        renderer=_PdfOnly(),
    )

    preview = service.documents(["naas_abi"])

    assert preview["total"] == 3
    assert preview["ingestable"] == 1
    assert preview["unsupported"] == 2
    by_name = {d["name"]: d["supported"] for d in preview["documents"]}
    assert by_name == {"events.json": False, "s.pkl": False, "x.pdf": True}


def test_already_ingested_counts_only_documents_that_could_be_ingested():
    service = PipelineAppService(
        request_store=FakeRequestStore(),
        object_storage=_Storage(tree={"mixed": ["a.pdf", "notes.json"]}),
        rows=_Rows({"file_name": [{"file_name": "a.pdf"}]}),
        renderer=_PdfOnly(),
    )

    preview = service.documents(["mixed"])

    assert preview["already_ingested"] == 1
    assert preview["ingestable"] == 1
