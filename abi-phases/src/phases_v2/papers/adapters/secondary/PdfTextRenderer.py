"""PDF to markdown, via the same libraries ``phases`` uses.

Keeping the conversion identical to v1 means the two modules' text — and so
their chunk boundaries — stay comparable even though they share no dataset.

Every failure is re-raised as :class:`RenderFailed`. That matters: the domain
catches exactly that type so one unreadable paper is reported and skipped
rather than ending the run.
"""

from __future__ import annotations

import io

from phases_v2.papers.interfaces import RenderFailed

SUFFIXES = (".pdf",)


class PdfTextRenderer:
    def handles(self, file_name: str) -> bool:
        return file_name.lower().endswith(SUFFIXES)

    def render(self, content: bytes, file_name: str) -> str:
        if not content:
            raise RenderFailed(f"{file_name} is empty")

        try:
            import pymupdf
            import pymupdf4llm

            with pymupdf.open(stream=io.BytesIO(content), filetype="pdf") as document:
                if document.page_count == 0:
                    raise RenderFailed(f"{file_name} has no pages")
                markdown = pymupdf4llm.to_markdown(document, show_progress=False)
        except RenderFailed:
            raise
        except Exception as failure:  # noqa: BLE001 - any library error is a failure to render
            raise RenderFailed(f"could not render {file_name}: {failure}") from failure

        if not markdown.strip():
            raise RenderFailed(f"{file_name} rendered to no text")
        return markdown
