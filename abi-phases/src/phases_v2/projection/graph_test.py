"""Projecting the datasets into this module's own named graphs."""

from phases_v2.ontologies import vocabulary as v
from phases_v2.projection.fakes import (
    FakeExtractionReader,
    FakeProjectionLedger,
    FakeTripleSink,
)
from phases_v2.projection.graph import project_graph
from phases_v2.projection.interfaces import GRAPH

V1_PAPERS = "http://ontology.naas.ai/graph/phases/papers"
V1_EXTRACTIONS = "http://ontology.naas.ai/graph/phases/extractions"


def _reader(n=1):
    return FakeExtractionReader(
        papers=[{"paper_id": f"p{i}", "file_name": f"{i}.pdf"} for i in range(n)],
        chunks=[
            {"chunk_id": f"c{i}", "paper_id": f"p{i}", "chunker_id": "w1", "seq": i,
             "text": f"chunk {i}"}
            for i in range(n)
        ],
        extractions=[
            {"extraction_id": f"e{i}", "chunk_id": f"c{i}", "model_id": "m",
             "prompt_id": "pr", "item_count": 1}
            for i in range(n)
        ],
        items=[
            {"item_id": f"i{i}", "extraction_id": f"e{i}", "chunk_id": f"c{i}",
             "paper_id": f"p{i}", "prompt_id": "pr", "seq": 0, "text": f"claim {i}"}
            for i in range(n)
        ],
    )


def _project(reader, sink=None, ledger=None):
    sink = sink or FakeTripleSink()
    ledger = ledger or FakeProjectionLedger()
    report = project_graph(reader=reader, sink=sink, ledger=ledger)
    return report, sink, ledger


def test_triples_land_in_this_modules_graphs():
    _report, sink, _ledger = _project(_reader())

    assert sink.count(str(v.EXTRACTIONS_GRAPH)) > 0
    assert sink.count(str(v.PAPERS_GRAPH)) > 0


def test_v1_graphs_are_never_written():
    _report, sink, _ledger = _project(_reader())

    assert V1_PAPERS not in sink.graphs
    assert V1_EXTRACTIONS not in sink.graphs


def test_an_extracted_item_can_be_traced_to_its_chunk_paper_model_and_prompt():
    _report, sink, _ledger = _project(_reader())

    triples = sink.graphs[str(v.EXTRACTIONS_GRAPH)]
    item = v.item_uri("i0")
    extraction = v.extraction_uri("e0")
    assert (item, v.DOC.extracted_from_chunk, v.chunk_uri("c0")) in triples
    assert (item, v.DOC.extracted_by, extraction) in triples
    assert (extraction, v.DOC.model_name, __import__("rdflib").Literal("m")) in triples
    assert any(
        s == extraction and p == v.DOC.prompt_hash for s, p, o in triples
    )


def test_re_projecting_unchanged_data_adds_nothing():
    reader = _reader()
    _report, sink, ledger = _project(reader)
    before = {name: set(triples) for name, triples in sink.graphs.items()}

    report, _sink, _ledger = _project(reader, sink=sink, ledger=ledger)

    assert report.projected == 0
    assert report.already_projected == 1
    assert {name: set(t) for name, t in sink.graphs.items()} == before


def test_only_new_rows_are_projected():
    reader = _reader()
    _report, sink, ledger = _project(reader)
    reader.add_extraction(
        {"extraction_id": "e9", "chunk_id": "c9", "model_id": "m", "prompt_id": "pr",
         "item_count": 1},
        items=[{"item_id": "i9", "extraction_id": "e9", "chunk_id": "c9",
                "paper_id": "p0", "prompt_id": "pr", "seq": 0, "text": "new claim"}],
    )

    report, _sink, _ledger = _project(reader, sink=sink, ledger=ledger)

    assert report.projected == 1


def test_an_interrupted_run_completes_without_duplicating():
    # The ledger is written after the triples, so a crash between them leaves
    # the row unrecorded and it is re-projected — which RDF absorbs, because
    # inserting the same triple twice is a no-op.
    reader = _reader(n=2)
    sink = FakeTripleSink()
    ledger = FakeProjectionLedger()
    project_graph(reader=reader, sink=sink, ledger=ledger)
    ledger.keys[GRAPH].discard("e1")  # pretend the ledger write was lost
    before = {name: set(t) for name, t in sink.graphs.items()}

    report = project_graph(reader=reader, sink=sink, ledger=ledger)

    assert report.projected == 1
    assert {name: set(t) for name, t in sink.graphs.items()} == before


def test_the_graph_can_be_rebuilt_from_the_datasets_alone():
    reader = _reader(n=2)
    _report, first, _ledger = _project(reader)

    _report2, second, _ledger2 = _project(reader)

    assert {n: set(t) for n, t in second.graphs.items()} == {
        n: set(t) for n, t in first.graphs.items()
    }


def test_nothing_to_project_writes_nothing():
    sink = FakeTripleSink()

    report = project_graph(
        reader=FakeExtractionReader(), sink=sink, ledger=FakeProjectionLedger()
    )

    assert report.projected == 0
    assert sink.inserts == 0


def test_a_large_projection_is_written_in_batches_each_then_recorded():
    reader = _reader(n=5)
    sink = FakeTripleSink()
    ledger = FakeProjectionLedger()
    recorded_after_insert: list[int] = []
    record = ledger.record

    def record_and_count(target, keys):
        recorded_after_insert.append(sink.inserts)
        record(target, keys)

    ledger.record = record_and_count

    report = project_graph(reader=reader, sink=sink, ledger=ledger, batch_size=2)

    assert report.projected == 5
    # Three batches, each a corpus insert and an extraction insert, each
    # recorded only once its triples are in.
    assert sink.inserts == 6
    assert recorded_after_insert == [2, 4, 6]
    assert ledger.keys[GRAPH] == {f"e{i}" for i in range(5)}
    _report, unbatched, _ledger = _project(_reader(n=5))
    assert {n: set(t) for n, t in sink.graphs.items()} == {
        n: set(t) for n, t in unbatched.graphs.items()
    }


def test_a_batch_that_fails_leaves_the_earlier_batches_recorded():
    reader = _reader(n=5)
    ledger = FakeProjectionLedger()

    class FailingSink(FakeTripleSink):
        def insert(self, graph_uri, triples):
            if self.inserts == 2:
                raise ConnectionError("timed out")
            super().insert(graph_uri, triples)

    try:
        project_graph(reader=reader, sink=FailingSink(), ledger=ledger, batch_size=2)
    except ConnectionError:
        pass

    assert ledger.keys[GRAPH] == {"e0", "e1"}
    report = project_graph(
        reader=reader, sink=FakeTripleSink(), ledger=ledger, batch_size=2
    )
    assert report.already_projected == 2
    assert report.projected == 3


class _RecordingSink(FakeTripleSink):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[tuple] = []

    def insert(self, graph_uri, triples):
        self.sent.extend(triples)
        super().insert(graph_uri, triples)


def test_a_chunk_shared_by_several_batches_is_sent_once():
    one = _reader()
    reader = FakeExtractionReader(
        papers=one.papers(),
        chunks=one.chunks(),
        extractions=[
            {"extraction_id": f"e{n}", "chunk_id": "c0", "model_id": "m",
             "prompt_id": f"pr{n}", "item_count": 0}
            for n in range(4)
        ],
    )
    sink = _RecordingSink()

    report = project_graph(
        reader=reader, sink=sink, ledger=FakeProjectionLedger(), batch_size=2
    )

    assert report.projected == 4
    texts = [t for t in sink.sent if t[1] == v.DOC.chunk_text]
    assert len(texts) == 1
    # Two batches: the corpus with the first, the extractions of each.
    assert sink.inserts == 3
