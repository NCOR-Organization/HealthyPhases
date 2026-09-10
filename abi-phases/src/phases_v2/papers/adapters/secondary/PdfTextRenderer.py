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
                if not markdown.strip():
                    # Layout detection can miss image-only pages even with OCR
                    # available. Fall back only when it produced no text.
                    pages = []
                    for page in document:
                        text = page.get_text(sort=True)
                        if not text.strip() and page.get_images():
                            text_page = page.get_textpage_ocr(
                                language="eng", dpi=150, full=True
                            )
                            text = page.get_text(textpage=text_page, sort=True)
                        pages.append(text)
                    markdown = "\n\n".join(pages)
        except RenderFailed:
            raise
        except Exception as failure:  # noqa: BLE001 - any library error is a failure to render
            raise RenderFailed(f"could not render {file_name}: {failure}") from failure

        if not markdown.strip():
            raise RenderFailed(f"{file_name} rendered to no text")
        return markdown
