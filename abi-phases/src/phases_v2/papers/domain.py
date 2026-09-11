"""Discovering papers under storage locations and recording them.

A paper's identity is its content, so the same file at two paths is one paper
and is never extracted twice. Everything already recorded with rendered text is
skipped, which is what makes an interrupted run safe to restart and a re-run
over an unchanged corpus free.

One failure never ends a run: a location that does not exist and a paper that
cannot be read are both recorded on the report, and the rest continues.
"""

from __future__ import annotations

import mimetypes
from datetime import UTC, datetime

from phases_v2 import identity
from phases_v2.papers.interfaces import (
    IngestReport,
    ObjectNotFound,
    ObjectSource,
    PaperRecord,
    PaperStore,
    RenderFailed,
    TextRenderer,
)

TEXT_PREFIX = "phases_v2_text"


def ingest(
    locations: list[str],
    *,
    source: ObjectSource,
    renderer: TextRenderer,
    papers: PaperStore,
    text_prefix: str = TEXT_PREFIX,
) -> IngestReport:
    """Discover every paper beneath ``locations`` and record what is new."""
    report = IngestReport()

    # One read for the whole run. A lookup per object would be a round trip
    # per object on every re-run, which is the common case.
    known = papers.already_ingested()

    discovered = _discover(locations, source, report)
    if not discovered:
        return report

    records: list[PaperRecord] = []
    seen: set[str] = set()
    now = datetime.now(UTC)

    for location, key, content in discovered:
        paper_id = identity.paper_id(content)

        # Twice in one run, or already recorded with its text: either way
        # there is nothing left to do for this content.
        if paper_id in seen:
            continue
        if known.get(paper_id):
            seen.add(paper_id)
            report.paper_ids.append(paper_id)
            report.skipped += 1
            continue
        seen.add(paper_id)

        file_name = key.rsplit("/", 1)[-1]

        # An object storage root holds other modules' data too. Something no
        # renderer claims is not a paper, so it is skipped rather than recorded
        # as a failed one — otherwise pointing a run at the wrong prefix fills
        # the dataset with noise.
        if not renderer.handles(file_name):
            report.unsupported += 1
            continue

        try:
            text = renderer.render(content, file_name)
        except RenderFailed as failure:
            report.failed_papers[f"{location}/{key}"] = str(failure)
            continue

        text_key = f"{paper_id}.md"
        source.put_object(text_prefix, text_key, text.encode("utf-8"))

        report.paper_ids.append(paper_id)
        records.append(
            PaperRecord(
                paper_id=paper_id,
                storage_prefix=location,
                storage_key=key,
                file_name=file_name,
                content_sha256=paper_id,
                size_bytes=len(content),
                mime_type=mimetypes.guess_type(file_name)[0],
                text_key=text_key,
                discovered_at=now,
            )
        )

    if records:
        papers.save(records)
    report.ingested = len(records)
    return report


def _discover(
    locations: list[str], source: ObjectSource, report: IngestReport
) -> list[tuple[str, str, bytes]]:
    """Read every object beneath each location, noting locations that fail."""
    found: list[tuple[str, str, bytes]] = []
    for location in locations:
        try:
            keys = source.list_objects_recursive(location)
        except ObjectNotFound as failure:
            report.failed_locations[location] = str(failure)
            continue
        for key in keys:
            found.append((location, key, source.get_object(location, key)))
    report.discovered = len(found)
    return found
