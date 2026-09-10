"""Embedding chunks and extracted items into this module's own collections."""

from phases_v2.projection.fakes import (
    FakeEmbedder,
    FakeExtractionReader,
    FakeProjectionLedger,
    FakeVectorSink,
)
from phases_v2.projection.interfaces import VECTOR_CHUNKS, VECTOR_ITEMS
from phases_v2.projection.vectors import (
    CHUNKS_COLLECTION,
    ITEMS_COLLECTION,
    project_vectors,
)

V1_COLLECTIONS = {"chunks", "extracted_items", "axioms", "labels"}


def _reader(n=2):
    return FakeExtractionReader(
        papers=[{"paper_id": f"p{i}", "file_name": f"{i}.pdf"} for i in range(n)],
        chunks=[
            {
                "chunk_id": f"c{i}",
                "paper_id": f"p{i}",
                "chunker_id": "w1",
                "seq": i,
                "text": f"chunk {i}",
            }
            for i in range(n)
        ],
        extractions=[
            {
                "extraction_id": f"e{i}",
                "chunk_id": f"c{i}",
                "model_id": "m",
                "prompt_id": "pr",
                "item_count": 1,
            }
            for i in range(n)
        ],
        items=[
            {
                "item_id": f"i{i}",
                "extraction_id": f"e{i}",
                "chunk_id": f"c{i}",
                "paper_id": f"p{i}",
                "prompt_id": "pr",
                "seq": 0,
                "text": f"claim {i}",
            }
            for i in range(n)
        ],
    )


def _project(reader, sink=None, ledger=None, embedder=None):
    sink = sink or FakeVectorSink()
    ledger = ledger or FakeProjectionLedger()
    embedder = embedder or FakeEmbedder()
    report = project_vectors(reader=reader, embedder=embedder, sink=sink, ledger=ledger)
    return report, sink, ledger, embedder


def test_chunks_and_items_go_to_their_own_collections():
    _r, sink, _l, _e = _project(_reader())

    assert sink.count(CHUNKS_COLLECTION) == 2
    assert sink.count(ITEMS_COLLECTION) == 2


def test_the_collections_are_not_the_ones_v1_uses():
    assert CHUNKS_COLLECTION not in V1_COLLECTIONS
    assert ITEMS_COLLECTION not in V1_COLLECTIONS
    assert CHUNKS_COLLECTION.startswith("phases_v2")
    assert ITEMS_COLLECTION.startswith("phases_v2")


def test_a_chunk_vector_resolves_to_its_chunk_and_paper():
    _r, sink, _l, _e = _project(_reader())

    doc, _vector = sink.collections[CHUNKS_COLLECTION]["c0"]
    assert doc.metadata["chunk_id"] == "c0"
    assert doc.metadata["paper_id"] == "p0"


def test_an_item_vector_resolves_to_everything_that_produced_it():
    _r, sink, _l, _e = _project(_reader())

    doc, _vector = sink.collections[ITEMS_COLLECTION]["i0"]
    assert doc.metadata["item_id"] == "i0"
    assert doc.metadata["extraction_id"] == "e0"
    assert doc.metadata["chunk_id"] == "c0"
    assert doc.metadata["paper_id"] == "p0"
    assert doc.metadata["model_id"] == "m"
    assert doc.metadata["prompt_id"] == "pr"


def test_re_running_embeds_nothing_and_changes_nothing():
    reader = _reader()
    _r, sink, ledger, _e = _project(reader)
    before = {name: dict(c) for name, c in sink.collections.items()}

    report, _s, _l, embedder = _project(reader, sink=sink, ledger=ledger)

    assert embedder.embedded == []
    assert report.projected == 0
    assert {name: dict(c) for name, c in sink.collections.items()} == before


def test_only_new_rows_are_embedded():
    reader = _reader()
    _r, sink, ledger, _e = _project(reader)
    reader.add_extraction(
        {
            "extraction_id": "e9",
            "chunk_id": "c9",
            "model_id": "m",
            "prompt_id": "pr",
            "item_count": 1,
        },
        items=[
            {
                "item_id": "i9",
                "extraction_id": "e9",
                "chunk_id": "c9",
                "paper_id": "p0",
                "prompt_id": "pr",
                "seq": 0,
                "text": "new claim",
            }
        ],
    )

    _report, _s, _l, embedder = _project(reader, sink=sink, ledger=ledger)

    assert embedder.embedded == ["new claim"]


def test_an_interrupted_run_finishes_without_re_embedding_what_it_stored():
    reader = _reader()
    _r, sink, ledger, _e = _project(reader)
    ledger.keys[VECTOR_ITEMS].discard("i1")

    _report, _s, _l, embedder = _project(reader, sink=sink, ledger=ledger)

    assert embedder.embedded == ["claim 1"]


def test_the_two_targets_are_tracked_separately():
    reader = _reader()
    _r, _s, ledger, _e = _project(reader)

    assert ledger.projected_keys(VECTOR_CHUNKS) == {"c0", "c1"}
    assert ledger.projected_keys(VECTOR_ITEMS) == {"i0", "i1"}


def test_collections_are_created_before_anything_is_stored():
    _r, sink, _l, _e = _project(_reader(n=0))

    assert CHUNKS_COLLECTION in sink.collections
    assert ITEMS_COLLECTION in sink.collections


def test_nothing_to_embed_calls_the_embedder_not_at_all():
    _report, _s, _l, embedder = _project(_reader(n=0))

    assert embedder.embedded == []


def test_later_batch_failure_preserves_checkpoints_for_retry(monkeypatch):
    import pytest

    from phases_v2.projection import vectors

    monkeypatch.setattr(vectors, "PROJECTION_BATCH_SIZE", 2)
    reader = _reader(n=5)
    ledger = FakeProjectionLedger()
    sink = FakeVectorSink()

    class InterruptedEmbedder(FakeEmbedder):
        calls = 0

        def embed(self, texts):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("temporary provider failure")
            return super().embed(texts)

    with pytest.raises(RuntimeError, match="provider failure"):
        _project(reader, ledger=ledger, sink=sink, embedder=InterruptedEmbedder())
    assert ledger.projected_keys(VECTOR_CHUNKS) == {"c0", "c1"}
    report, _, _, embedder = _project(reader, ledger=ledger, sink=sink)
    assert report.already_projected == 2
    assert report.projected == 8
    assert "chunk 0" not in embedder.embedded
    assert "chunk 1" not in embedder.embedded
    assert sink.count(CHUNKS_COLLECTION) == 5
    assert sink.count(ITEMS_COLLECTION) == 5


def test_missing_vectors_do_not_mark_documents_as_projected():
    import pytest

    class BrokenEmbedder(FakeEmbedder):
        def embed(self, texts):
            return []

    ledger = FakeProjectionLedger()
    with pytest.raises(ValueError, match="different number"):
        _project(_reader(), ledger=ledger, embedder=BrokenEmbedder())
    assert ledger.projected_keys(VECTOR_CHUNKS) == set()
