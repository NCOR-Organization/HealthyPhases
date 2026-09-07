"""The PDF renderer, held to the shared renderer contract."""

import pytest

from phases_v2.papers.adapters.secondary.PdfTextRenderer import PdfTextRenderer
from phases_v2.papers.interfaces import RenderFailed
from phases_v2.papers.tests.text_renderer__secondary_adapter__generic_test import (
    TextRendererContract,
)

SAMPLE_PHRASE = "Solitude and health outcomes"


def _make_pdf(text: str = SAMPLE_PHRASE) -> bytes:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text, fontsize=14)
    return document.tobytes()


class TestPdfTextRenderer(TextRendererContract):
    @pytest.fixture
    def renderer(self) -> PdfTextRenderer:
        return PdfTextRenderer()

    def sample_document(self) -> tuple[bytes, str]:
        return _make_pdf(), "study.pdf"

    def sample_text(self) -> str:
        return SAMPLE_PHRASE

    def test_it_claims_pdfs_whatever_the_case(self, renderer):
        assert renderer.handles("STUDY.PDF")
        assert renderer.handles("study.Pdf")

    def test_a_pdf_with_no_extractable_text_is_a_failure_not_empty_output(
        self, renderer
    ):
        # An image-only scan renders to nothing. Recording it as a successful
        # ingestion with empty text would let it reach chunking and quietly
        # produce no chunks at all.
        import pymupdf

        document = pymupdf.open()
        document.new_page()
        blank = document.tobytes()

        with pytest.raises(RenderFailed, match="no text"):
            renderer.render(blank, "scan.pdf")
