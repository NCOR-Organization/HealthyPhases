"""HTTP pagination and complete CSV exports for reverse search."""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import asdict
from tempfile import SpooledTemporaryFile
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from phases_v2.app.contracts.pipeline_validation import validate_message
from phases_v2.search.domain import SearchService

PREFIX = "/phases_v2/api/search"
CSV_COLUMNS = [
    "query",
    "mode",
    "item_id",
    "extracted_text",
    "score",
    "model_id",
    "prompt_id",
    "prompt_name",
    "prompt_template",
    "paper_id",
    "paper_name",
    "source_path",
    "chunk_id",
    "chunk_seq",
    "chunk_text",
]


def search_filters(
    q: str,
    score_threshold: float | None = None,
    prompt: Annotated[list[str] | None, Query()] = None,
    model: Annotated[list[str] | None, Query()] = None,
    path: Annotated[list[str] | None, Query()] = None,
    snapshot: int | None = None,
):
    return {
        "query": q,
        "score_threshold": score_threshold,
        "prompts": prompt or [],
        "models": model or [],
        "paths": path or [],
        "snapshot": snapshot,
    }


def _csv_cell(value):
    if isinstance(value, str) and (
        re.match(r"\s*[=+@-]", value) or value.startswith(("\t", "\r", "\n"))
    ):
        return "'" + value
    return "" if value is None else value


def _csv_line(values):
    output = io.StringIO(newline="")
    csv.writer(output, quoting=csv.QUOTE_ALL).writerow([_csv_cell(v) for v in values])
    return output.getvalue().encode("utf-8")


def _csv_document(hits, query, mode):
    yield b"\xef\xbb\xbf"
    yield _csv_line(CSV_COLUMNS)
    for hit in hits:
        row = {"query": query, "mode": mode, **asdict(hit)}
        yield _csv_line(row[column] for column in CSV_COLUMNS)


def build_router(service: SearchService) -> APIRouter:
    router = APIRouter(prefix=PREFIX, tags=["phases_v2-search"])

    def view(mode, filters, limit=25, offset=0):
        payload = {"mode": mode, "limit": limit, "offset": offset, **filters}
        try:
            validate_message("SearchQuery", payload)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        options = {key: value for key, value in filters.items() if key != "snapshot"}
        scoped, snapshot = service.read_view(filters["snapshot"])
        return scoped, snapshot, options

    def unavailable(error):
        logging.getLogger(__name__).exception("Reverse search failed")
        return HTTPException(
            status_code=503, detail="Search storage is unavailable. Please retry."
        )

    def page(mode, limit, offset, filters):
        try:
            scoped, snapshot, options = view(mode, filters, limit, offset)
            hits, total = scoped.page(mode, limit=limit, offset=offset, **options)
        except HTTPException:
            raise
        except Exception as error:
            raise unavailable(error) from error
        following = offset + len(hits)
        return {
            "query": filters["query"],
            "mode": mode,
            "count": total,
            "total": total,
            "page_count": len(hits),
            "offset": offset,
            "snapshot": snapshot,
            "has_more": following < total,
            "next_offset": following if following < total else None,
            "hits": [asdict(hit) for hit in hits],
        }

    @router.get("/semantic")
    def semantic_search(
        k: int = 10,
        offset: int = 0,
        filters: dict = Depends(search_filters),
    ):
        return page("semantic", k, offset, filters)

    @router.get("/keyword")
    def keyword_search(
        limit: int = 25,
        offset: int = 0,
        filters: dict = Depends(search_filters),
    ):
        return page("keyword", limit, offset, filters)

    @router.get("/export")
    def export_csv(mode: str, filters: dict = Depends(search_filters)):
        # Finish reading before sending headers: a store failure must not look
        # like a successful, truncated export. Large exports spill to disk.
        output = SpooledTemporaryFile(max_size=8 * 1024 * 1024)  # noqa: SIM115 - response owns lifetime
        try:
            scoped, _, options = view(mode, filters)
            output.writelines(
                _csv_document(scoped.all_hits(mode, **options), filters["query"], mode)
            )
            length = output.tell()
            output.seek(0)
        except HTTPException:
            output.close()
            raise
        except Exception as error:
            output.close()
            raise unavailable(error) from error

        def chunks():
            try:
                while block := output.read(64 * 1024):
                    yield block
            finally:
                output.close()

        return StreamingResponse(
            chunks(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="phases-v2-search.csv"',
                "Content-Length": str(length),
            },
            background=BackgroundTask(output.close),
        )

    @router.get("/prompts")
    def prompts():
        return {"prompts": service.list_prompts()}

    @router.get("/models")
    def models():
        return {"models": service.list_models()}

    @router.get("/paths")
    def paths():
        return {"paths": service.list_paths()}

    return router


def register(app: FastAPI, service: SearchService) -> None:
    app.include_router(build_router(service))
