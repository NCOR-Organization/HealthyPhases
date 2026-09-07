"""Shared conformance suite for text renderers.

Subclass and supply the ``renderer`` fixture plus a sample document. Every
renderer is then held to the same observable behaviour: it says what it
handles, it produces text, and it fails in a way one bad paper cannot turn
into a failed run.
"""

from abc import ABC, abstractmethod

import pytest

from phases_v2.papers.interfaces import RenderFailed, TextRenderer


class TextRendererContract(ABC):
    @pytest.fixture
    @abstractmethod
    def renderer(self) -> TextRenderer:
        raise NotImplementedError()

    @abstractmethod
    def sample_document(self) -> tuple[bytes, str]:
        """A document this renderer handles, as ``(content, file_name)``."""

    @abstractmethod
    def sample_text(self) -> str:
        """A phrase that must appear in the rendered output."""

    def test_it_renders_a_document_it_handles(self, renderer):
        content, file_name = self.sample_document()

        rendered = renderer.render(content, file_name)

        assert isinstance(rendered, str)
        assert self.sample_text() in rendered

    def test_it_claims_the_file_types_it_handles(self, renderer):
        _content, file_name = self.sample_document()

        assert renderer.handles(file_name)

    def test_it_does_not_claim_a_file_type_it_cannot_read(self, renderer):
        assert not renderer.handles("notes.xyz")

    def test_unreadable_bytes_raise_render_failed_rather_than_anything_else(
        self, renderer
    ):
        # One unreadable paper must not end a run, so the domain catches
        # exactly this type. A renderer that leaks a library-specific error
        # would abort the whole ingestion.
        _content, file_name = self.sample_document()

        with pytest.raises(RenderFailed):
            renderer.render(b"this is definitely not a document", file_name)

    def test_empty_content_raises_render_failed(self, renderer):
        _content, file_name = self.sample_document()

        with pytest.raises(RenderFailed):
            renderer.render(b"", file_name)

    def test_rendering_is_deterministic(self, renderer):
        content, file_name = self.sample_document()

        assert renderer.render(content, file_name) == renderer.render(
            content, file_name
        )
