"""The coverage report, on in-memory corpora."""

import pytest

from phases_v2.coverage.domain import UnknownPrompt, build_report, render_text, to_dict
from phases_v2.coverage.fakes import FakeCoverageReader
from phases_v2.coverage.interfaces import (
    COLLECTION,
    EVERYTHING,
    GRAPH,
    PUBMED_SEARCH,
    RELATIONS,
    VECTOR_CHUNKS,
    VECTOR_ITEMS,
    Collection,
    SavedSearch,
    Selection,
)
from phases_v2.paper_collections.domain import folder_member, member_from_command
from phases_v2.paper_collections.interfaces import Artifact
from phases_v2.prompts.domain import PromptTemplate

GPT = "openai/gpt-4.1-mini"
SONNET = "anthropic/claude-sonnet-4.6"
CHUNKER = "window_1_test"
WHAT = PromptTemplate("solitude_what", "What? {chunk_text}", "what")
RELATIONS_PROMPT = PromptTemplate(
    "probabilistic_processes", "Relations? {chunk_text}", "relations"
)
EARLIER = PromptTemplate("solitude_what", "Earlier what? {chunk_text}", "what")
DECLARED = (WHAT, RELATIONS_PROMPT, EARLIER)
CURRENT = (WHAT, RELATIONS_PROMPT)
SELECTION = Selection(
    models=(GPT,),
    prompt_ids=(WHAT.prompt_id, RELATIONS_PROMPT.prompt_id),
    chunker_id=CHUNKER,
)
PAPER_A = "a" * 64
PAPER_B = "b" * 64
PAPER_C = "c" * 64


def folder_pdf(prefix, name, paper_id=None):
    return Artifact(prefix, name, content_sha256=paper_id, name=name)


def pubmed_pdf(paper_id, pmid):
    return Artifact(
        "pubmed/pdfs", f"{pmid}.pdf", content_sha256=paper_id, name=pmid, pmid=pmid
    )


def corpus(**overrides) -> FakeCoverageReader:
    """One collection holding one ingested, chunked paper that is fully done."""
    reader = FakeCoverageReader(
        prompts={
            WHAT.prompt_id: (WHAT.name, WHAT.output_key),
            RELATIONS_PROMPT.prompt_id: (
                RELATIONS_PROMPT.name,
                RELATIONS_PROMPT.output_key,
            ),
            EARLIER.prompt_id: (EARLIER.name, EARLIER.output_key),
        },
        **overrides,
    )
    reader.sources.folders["phases_v2/solitude"] = [
        folder_pdf("phases_v2/solitude", "a.pdf")
    ]
    reader.papers[PAPER_A] = folder_pdf("phases_v2/solitude", "a.pdf", PAPER_A)
    reader.sources.ingested[PAPER_A] = reader.papers[PAPER_A]
    reader.collection_rows.append(
        Collection("col-1", "solitude", [folder_member("phases_v2/solitude")])
    )
    for seq in range(2):
        chunk = f"{PAPER_A[:4]}-{seq}"
        reader.chunks.append(
            {"chunk_id": chunk, "paper_id": PAPER_A, "chunker_id": CHUNKER}
        )
        reader.projected.add((VECTOR_CHUNKS, chunk))
        for prompt in CURRENT:
            succeed(reader, chunk, prompt)
    return reader


def succeed(reader, chunk, prompt, model=GPT, *, projected=True):
    row = {
        "chunk_id": chunk,
        "model_id": model,
        "prompt_id": prompt.prompt_id,
        "status": "succeeded",
        "raw_response": "{}",
        "error": None,
    }
    reader.extractions.append(row)
    extraction = reader.extraction_id(row)
    item = f"{extraction}#0"
    reader.items.append(
        {"item_id": item, "extraction_id": extraction, "prompt_id": prompt.prompt_id}
    )
    if projected:
        reader.projected |= {(GRAPH, extraction), (VECTOR_ITEMS, item)}
        if prompt.output_key == "relations":
            reader.projected.add((RELATIONS, item))
    return row


def report_for(reader, selection=SELECTION):
    return build_report(reader, selection, declared=DECLARED, current=CURRENT)


def source(report, kind, index=0):
    return [s for s in report.sources if s.kind == kind][index]


def coverage(src, prompt=WHAT, model=GPT):
    return next(
        c
        for c in src.coverage
        if c.prompt_id == prompt.prompt_id and c.model_id == model
    )


def test_a_complete_source_has_nothing_outstanding():
    report = report_for(corpus())

    col = source(report, COLLECTION)
    assert (col.ids, col.names, len(col.documents)) == (["col-1"], ["solitude"], 1)
    assert col.not_ingested == col.not_chunked == []
    for prompt in CURRENT:
        row = coverage(col, prompt)
        assert (row.chunks, row.succeeded, row.not_run) == (2, 2, 0)
        assert row.failed_calls == row.invalid_answers == {}
    assert all(b.outstanding == 0 for b in report.backlog)
    assert report.problems() == []


def test_chunks_with_no_extraction_are_not_run():
    reader = corpus()
    reader.chunks.append(
        {"chunk_id": "late", "paper_id": PAPER_A, "chunker_id": CHUNKER}
    )
    reader.projected.add((VECTOR_CHUNKS, "late"))

    report = report_for(reader)

    row = coverage(source(report, COLLECTION))
    assert (row.chunks, row.succeeded, row.not_run) == (3, 2, 1)
    assert (
        "collection solitude: solitude_what × openai/gpt-4.1-mini: 1 chunks not run"
        in (report.problems())
    )


def test_a_model_that_never_ran_has_every_chunk_not_run():
    report = report_for(corpus(), Selection((SONNET,), (WHAT.prompt_id,), CHUNKER))

    row = coverage(source(report, COLLECTION), model=SONNET)
    assert (row.chunks, row.not_run) == (2, 2)


def test_a_failed_call_and_an_invalid_answer_are_told_apart():
    reader = corpus()
    chunk = reader.chunks[0]["chunk_id"]
    reader.extractions = [e for e in reader.extractions if e["chunk_id"] != chunk]
    reader.extractions += [
        {
            "chunk_id": chunk,
            "model_id": GPT,
            "prompt_id": WHAT.prompt_id,
            "status": "failed",
            "raw_response": None,
            "error": "extraction tool call failed: Connection error.",
        },
        {
            "chunk_id": chunk,
            "model_id": GPT,
            "prompt_id": RELATIONS_PROMPT.prompt_id,
            "status": "failed",
            "raw_response": '{"relations": [{"direction": "alters"}]}',
            "error": "extraction tool call failed: invalid RelationsOutput",
        },
    ]

    report = report_for(reader)

    col = source(report, COLLECTION)
    what, relations = coverage(col, WHAT), coverage(col, RELATIONS_PROMPT)
    assert what.failed_calls == {"extraction tool call failed: Connection error.": 1}
    assert what.invalid_answers == {}
    assert relations.invalid_answers == {
        "extraction tool call failed: invalid RelationsOutput": 1
    }
    assert relations.failed_calls == {}
    assert {(f.prompt_id, f.state, f.count) for f in report.failures} == {
        (WHAT.prompt_id, "failed_call", 1),
        (RELATIONS_PROMPT.prompt_id, "invalid_answer", 1),
    }
    problems = report.problems()
    assert any("1 failed calls" in p for p in problems)
    # Invalid answers are listed, never failed on.
    assert not any("invalid" in p for p in problems)


def test_a_pdf_that_was_never_ingested_is_listed():
    reader = corpus()
    reader.sources.folders["phases_v2/gerotranscendence"] = [
        folder_pdf("phases_v2/gerotranscendence", "g.pdf", PAPER_C)
    ]
    reader.collection_rows.append(
        Collection(
            "col-2", "gerotranscendence", [folder_member("phases_v2/gerotranscendence")]
        )
    )

    report = report_for(reader)

    gero = next(s for s in report.sources if s.ids == ["col-2"])
    assert [d.path for d in gero.not_ingested] == ["phases_v2/gerotranscendence/g.pdf"]
    assert all(c.chunks == 0 for c in gero.coverage)
    assert "collection gerotranscendence: 1 PDFs not ingested" in report.problems()
    assert len(source(report, EVERYTHING).not_ingested) == 1


def test_an_ingested_paper_with_no_chunks_is_not_chunked():
    reader = corpus()
    reader.papers[PAPER_B] = folder_pdf("phases_v2/solitude", "b.pdf", PAPER_B)
    reader.sources.ingested[PAPER_B] = reader.papers[PAPER_B]
    reader.sources.folders["phases_v2/solitude"].append(
        folder_pdf("phases_v2/solitude", "b.pdf")
    )

    col = source(report_for(reader), COLLECTION)

    assert [d.paper_id for d in col.not_chunked] == [PAPER_B]
    assert col.not_ingested == []


def test_the_same_pdf_reached_through_two_members_counts_once():
    reader = corpus()
    reader.collection_rows[0] = Collection(
        "col-1",
        "solitude",
        [
            folder_member("phases_v2/solitude"),
            member_from_command({"paper": {"paper_id": PAPER_A}}),
        ],
    )

    report = report_for(reader)

    col = source(report, COLLECTION)
    assert len(col.documents) == 1
    assert coverage(col).chunks == 2


def test_searches_that_resolve_to_the_same_pdfs_are_one_source():
    reader = corpus()
    same = [pubmed_pdf(PAPER_A, "1"), pubmed_pdf(PAPER_B, "2")]
    reader.sources.queries = {"q-1": same, "q-2": list(same), "q-3": same[:1]}
    reader.searches = [
        SavedSearch("q-1", "gerotranscendence"),
        SavedSearch("q-2", "gerotranscendence"),
        SavedSearch("q-3", "solitude AND shyness"),
        SavedSearch("q-empty", "nothing downloaded"),
    ]

    report = report_for(reader)

    searches = [s for s in report.sources if s.kind == PUBMED_SEARCH]
    assert [(s.ids, len(s.documents)) for s in searches] == [
        (["q-1", "q-2"], 2),
        (["q-3"], 1),
    ]
    assert searches[0].label == "gerotranscendence"
    assert [d.pmid for d in searches[0].not_ingested] == ["2"]


def test_everything_counts_each_paper_once_by_content():
    reader = corpus()
    # Paper A is in a collection, downloaded from PubMed and ingested.
    reader.downloaded = [pubmed_pdf(PAPER_A, "1"), pubmed_pdf(PAPER_B, "2")]
    reader.papers[PAPER_C] = folder_pdf("phases_v2/elsewhere", "c.pdf", PAPER_C)

    everything = source(report_for(reader), EVERYTHING)

    assert sorted(d.paper_id for d in everything.documents) == [
        PAPER_A,
        PAPER_B,
        PAPER_C,
    ]
    assert [d.paper_id for d in everything.not_ingested] == [PAPER_B]
    assert [d.paper_id for d in everything.not_chunked] == [PAPER_C]


def test_a_prompt_name_no_longer_declared_is_flagged():
    reader = corpus()
    reader.prompts["logical_sentences_1624"] = ("logical_sentences", "results")
    reader.extractions.append(
        {
            "chunk_id": reader.chunks[0]["chunk_id"],
            "model_id": GPT,
            "prompt_id": "logical_sentences_1624",
            "status": "succeeded",
        }
    )

    report = report_for(reader)

    assert report.undeclared_prompts == ["logical_sentences"]
    states = {
        v["prompt_id"]: (v["declared"], v["current"])
        for v in to_dict(report)["prompt_versions"]
    }
    assert states["logical_sentences_1624"] == (False, False)
    assert states[EARLIER.prompt_id] == (True, False)
    assert states[WHAT.prompt_id] == (True, True)


def test_a_projection_backlog_is_counted_per_target():
    reader = corpus()
    chunk = reader.chunks[0]["chunk_id"]
    reader.extractions = [e for e in reader.extractions if e["chunk_id"] != chunk]
    reader.items = [i for i in reader.items if not i["item_id"].startswith(chunk)]
    reader.projected = {k for k in reader.projected if chunk not in k[1]}
    for prompt in CURRENT:
        succeed(reader, chunk, prompt, projected=False)
    # Outside the selection: counted overall, never failed on.
    succeed(reader, chunk, WHAT, model=SONNET, projected=False)
    reader.rejected_relations = {f"{chunk}:{GPT}:{RELATIONS_PROMPT.prompt_id}#0": "bad"}

    report = report_for(reader)

    backlog = {b.target: (b.outstanding, b.selected) for b in report.backlog}
    assert backlog == {
        GRAPH: (3, 2),
        VECTOR_CHUNKS: (1, 1),
        VECTOR_ITEMS: (3, 2),
        RELATIONS: (1, 1),
    }
    check = report.relation_check
    assert (check.examined, check.rejected, check.rejected_selected) == (1, 1, 1)
    problems = report.problems()
    assert "projection vector_items: 2 outstanding" in problems
    # The one relation item outstanding is rejected by the contract: it can
    # never be projected, so it is listed rather than failed on.
    assert not any("probabilistic_relations_v1" in p for p in problems)


def test_unfinished_run_requests_are_listed():
    reader = corpus(
        requests=[
            {"request_id": "r1", "status": "succeeded"},
            {"request_id": "r2", "status": "failed", "error": "run exited"},
            {"request_id": "r3", "status": "pending"},
        ]
    )

    report = report_for(reader)

    assert report.run_requests_by_status == {"succeeded": 1, "failed": 1, "pending": 1}
    assert [(r["request_id"], r["error"]) for r in report.unfinished_requests] == [
        ("r2", "run exited"),
        ("r3", None),
    ]


def test_an_unknown_prompt_id_is_refused():
    with pytest.raises(UnknownPrompt, match="no-such-prompt"):
        report_for(corpus(), Selection((GPT,), ("no-such-prompt",), CHUNKER))


def test_an_unreadable_member_fails_the_strict_check():
    reader = corpus()
    reader.sources.unreachable.add("phases_v2/solitude")

    report = report_for(reader)

    assert source(report, COLLECTION).unreadable
    assert any("could not be read" in p for p in report.problems())


def test_the_text_report_names_every_section():
    text = render_text(report_for(corpus()))

    for heading in (
        "== collection: solitude",
        "== everything: everything we hold",
        "== Failures",
        "== Prompt versions",
        "== Run requests",
        "== Projection backlog",
        "== Strict check: passed",
    ):
        assert heading in text
