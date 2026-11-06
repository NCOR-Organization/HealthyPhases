"""Has every paper we hold run through every prompt, with this model?

:func:`build_report` answers it for every source of papers:

- each app collection that is not archived, resolved with
  :func:`phases_v2.paper_collections.domain.resolve`, as its page and a run on
  it resolve it;
- each saved PubMed search with downloaded PDFs. Searches that resolve to the
  same PDFs are one source, listing all their ids;
- everything we hold: every collection paper, every downloaded PubMed PDF and
  every ingested paper.

A paper's identity is its content, so a PDF reached twice, through two members
or two sources, counts once.

Everything is read through a :class:`CoverageReader` pinned to one snapshot.
Nothing here writes.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from phases_v2.coverage.interfaces import (
    COLLECTION,
    EVERYTHING,
    FAILED_CALL,
    NOT_RUN,
    PUBMED_SEARCH,
    RELATIONS,
    SUCCEEDED,
    TARGETS,
    Backlog,
    CoverageReader,
    FailureCount,
    PromptVersion,
    RelationCheck,
    Selection,
)
from phases_v2.paper_collections.domain import member_from_command, resolve
from phases_v2.paper_collections.interfaces import Artifact, Resolution
from phases_v2.prompts.domain import PromptTemplate

#: Run requests in these states are done; any other one is reported.
_DONE = "succeeded"
#: Longest error text kept in a report; the rest is cut.
_ERROR_CHARS = 300


class UnknownPrompt(ValueError):
    """A selected prompt id is neither declared nor stored."""


@dataclass(frozen=True)
class Document:
    path: str
    #: Its content hash, which is the id it has (or will have) once ingested.
    paper_id: str | None
    pmid: str | None = None


@dataclass
class PromptCoverage:
    """One source's chunks for one prompt version and model."""

    prompt_id: str
    prompt_name: str | None
    model_id: str
    chunks: int = 0
    succeeded: int = 0
    not_run: int = 0
    #: Reason → chunks, for calls that failed with no answer stored.
    failed_calls: dict[str, int] = field(default_factory=dict)
    #: Reason → chunks, for answers stored but not valid for the prompt.
    invalid_answers: dict[str, int] = field(default_factory=dict)

    @property
    def failed_call_count(self) -> int:
        return sum(self.failed_calls.values())

    @property
    def invalid_answer_count(self) -> int:
        return sum(self.invalid_answers.values())


@dataclass
class SourceReport:
    kind: str
    ids: list[str]
    names: list[str]
    documents: list[Document]
    not_ingested: list[Document]
    not_chunked: list[Document]
    coverage: list[PromptCoverage]
    #: Files beneath a folder member that no run can read, so not papers.
    unsupported: int = 0
    #: Members that could not be read, with the reason.
    unreadable: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return " | ".join(dict.fromkeys(self.names)) or ", ".join(self.ids)


@dataclass
class CoverageReport:
    snapshot: int | None
    selection: Selection
    prompt_names: dict[str, str | None]
    sources: list[SourceReport]
    failures: list[FailureCount]
    prompt_versions: list[PromptVersion]
    declared_prompt_ids: set[str]
    current_prompt_ids: set[str]
    undeclared_prompts: list[str]
    run_requests_by_status: dict[str, int]
    unfinished_requests: list[dict[str, Any]]
    backlog: list[Backlog]
    relation_check: RelationCheck

    def problems(self) -> list[str]:
        """What ``--strict`` fails on, for the selected prompts and models.

        Invalid answers are left out: some stay invalid after every retry, by
        design, and are listed rather than failed on.
        """
        found = []
        for source in self.sources:
            where = f"{source.kind} {source.label}"
            for member, reason in source.unreadable.items():
                found.append(f"{where}: member {member} could not be read: {reason}")
            if source.not_ingested:
                found.append(f"{where}: {len(source.not_ingested)} PDFs not ingested")
            if source.not_chunked:
                found.append(
                    f"{where}: {len(source.not_chunked)} ingested papers not chunked"
                )
            for row in source.coverage:
                what = f"{where}: {row.prompt_name or row.prompt_id} × {row.model_id}"
                if row.not_run:
                    found.append(f"{what}: {row.not_run} chunks not run")
                if row.failed_call_count:
                    found.append(f"{what}: {row.failed_call_count} failed calls")
        for backlog in self.backlog:
            outstanding = backlog.selected
            if backlog.target == RELATIONS:
                # Rejected items can never be projected; they are listed instead.
                outstanding -= self.relation_check.rejected_selected
            if outstanding:
                found.append(f"projection {backlog.target}: {outstanding} outstanding")
        return found


def build_report(
    reader: CoverageReader,
    selection: Selection,
    *,
    declared: Sequence[PromptTemplate],
    current: Sequence[PromptTemplate],
) -> CoverageReport:
    """Read every source and count what is done, failed and missing.

    ``declared`` are the prompt versions the code declares; ``current`` the one
    of each a new run uses.
    """
    versions = reader.prompt_versions()
    names: dict[str, str | None] = {v.prompt_id: v.name for v in versions}
    for prompt in declared:
        names.setdefault(prompt.prompt_id, prompt.name)
    unknown = [p for p in selection.prompt_ids if p not in names]
    if unknown:
        raise UnknownPrompt(
            "No prompt version has the id "
            + ", ".join(unknown)
            + ". Pass ids as the prompts dataset stores them, e.g. "
            + ", ".join(p.prompt_id for p in current[:2])
            + "."
        )

    sources = _sources(reader)
    ingested = {a.content_sha256 for a in reader.ingested_papers()}
    chunked = reader.chunked_papers(selection.chunker_id)

    scopes = {
        key: sorted({d.paper_id for d in docs if d.paper_id in ingested})
        for key, (_, docs) in sources.items()
    }
    coverage = _coverage(reader, scopes, selection, names)

    reports = []
    for key, (draft, docs) in sources.items():
        reports.append(
            SourceReport(
                kind=draft.kind,
                ids=draft.ids,
                names=draft.names,
                documents=docs,
                not_ingested=[d for d in docs if d.paper_id not in ingested],
                not_chunked=[
                    d
                    for d in docs
                    if d.paper_id in ingested and d.paper_id not in chunked
                ],
                coverage=coverage[key],
                unsupported=draft.unsupported,
                unreadable=draft.unreadable,
            )
        )

    declared_names = {p.name for p in declared}
    undeclared = sorted(
        {v.name or v.prompt_id for v in versions if v.extractions} - declared_names
    )
    requests = reader.run_requests()
    backlog = _complete_backlog(reader.projection_backlog(selection))
    relations = next(b for b in backlog if b.target == RELATIONS)
    return CoverageReport(
        snapshot=reader.snapshot(),
        selection=selection,
        prompt_names=names,
        sources=reports,
        failures=sorted(
            reader.failures(),
            key=lambda f: (
                names.get(f.prompt_id) or "",
                f.prompt_id,
                f.model_id,
                -f.count,
            ),
        ),
        prompt_versions=sorted(
            versions, key=lambda v: (v.name or "", -v.extractions, v.prompt_id)
        ),
        declared_prompt_ids={p.prompt_id for p in declared},
        current_prompt_ids={p.prompt_id for p in current},
        undeclared_prompts=undeclared,
        run_requests_by_status=dict(Counter(r["status"] for r in requests)),
        unfinished_requests=[_request(r) for r in requests if r["status"] != _DONE],
        backlog=backlog,
        relation_check=(
            reader.relation_check(selection)
            if relations.outstanding
            else RelationCheck(0, 0)
        ),
    )


# -- sources --------------------------------------------------------------


@dataclass
class _Draft:
    kind: str
    ids: list[str]
    names: list[str]
    unsupported: int = 0
    unreadable: dict[str, str] = field(default_factory=dict)


def _sources(reader: CoverageReader) -> dict[str, tuple[_Draft, list[Document]]]:
    member_sources = reader.member_sources()
    supported = reader.supported
    out: dict[str, tuple[_Draft, list[Document]]] = {}
    held: dict[str, Document] = {}

    for collection in sorted(
        reader.collections(), key=lambda c: (c.name.casefold(), c.collection_id)
    ):
        resolution = resolve(collection.members, member_sources, supported)
        docs = _documents(resolution)
        out[f"{COLLECTION}:{collection.collection_id}"] = (
            _Draft(
                COLLECTION,
                [collection.collection_id],
                [collection.name],
                unsupported=resolution.unsupported,
                unreadable=dict(resolution.failed),
            ),
            docs,
        )
        _hold(held, docs)

    # Searches that resolve to the same PDFs are one source.
    searches: dict[frozenset[str], tuple[_Draft, list[Document]]] = {}
    for search in sorted(reader.saved_searches(), key=lambda s: s.query_id):
        member = member_from_command({"pubmed_query": {"query_id": search.query_id}})
        resolution = resolve([member], member_sources, supported)
        docs = _documents(resolution)
        if not docs:
            continue
        same = frozenset(_key(d) for d in docs)
        if same in searches:
            draft = searches[same][0]
            draft.ids.append(search.query_id)
            draft.names.append(search.query)
        else:
            searches[same] = (
                _Draft(PUBMED_SEARCH, [search.query_id], [search.query]),
                docs,
            )
    for draft, docs in sorted(
        searches.values(), key=lambda s: (s[0].names[0].casefold(), s[0].ids[0])
    ):
        out[f"{PUBMED_SEARCH}:{draft.ids[0]}"] = (draft, docs)

    _hold(held, [_document(a) for a in reader.downloaded_pdfs()])
    _hold(held, [_document(a) for a in reader.ingested_papers()])
    out[EVERYTHING] = (
        _Draft(EVERYTHING, [EVERYTHING], ["everything we hold"]),
        list(held.values()),
    )
    return out


def _key(document: Document) -> str:
    return document.paper_id or f"path:{document.path}"


def _document(artifact: Artifact) -> Document:
    return Document(artifact.path, artifact.content_sha256, artifact.pmid)


def _documents(resolution: Resolution) -> list[Document]:
    return [_document(paper.artifact) for paper in resolution.papers]


def _hold(held: dict[str, Document], docs: list[Document]) -> None:
    for doc in docs:
        held.setdefault(_key(doc), doc)


# -- counts ---------------------------------------------------------------


def _coverage(
    reader: CoverageReader,
    scopes: dict[str, list[str]],
    selection: Selection,
    names: dict[str, str | None],
) -> dict[str, list[PromptCoverage]]:
    out: dict[str, dict[tuple[str, str], PromptCoverage]] = {
        key: {
            (prompt_id, model_id): PromptCoverage(
                prompt_id, names.get(prompt_id), model_id
            )
            for prompt_id in selection.prompt_ids
            for model_id in selection.models
        }
        for key in scopes
    }
    for count in reader.coverage(scopes, selection):
        row = out[count.scope][count.prompt_id, count.model_id]
        row.chunks += count.chunks
        if count.state == SUCCEEDED:
            row.succeeded += count.chunks
        elif count.state == NOT_RUN:
            row.not_run += count.chunks
        else:
            failed = (
                row.failed_calls if count.state == FAILED_CALL else row.invalid_answers
            )
            reason = _reason(count.reason)
            failed[reason] = failed.get(reason, 0) + count.chunks
    return {key: list(rows.values()) for key, rows in out.items()}


def _reason(reason: str | None) -> str:
    text = " ".join((reason or "").split()) or "(no error recorded)"
    return text if len(text) <= _ERROR_CHARS else text[: _ERROR_CHARS - 1] + "…"


def _complete_backlog(rows: list[Backlog]) -> list[Backlog]:
    by_target = {row.target: row for row in rows}
    return [by_target.get(t, Backlog(t, 0, 0)) for t in TARGETS]


def _request(row: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "request_id",
        "status",
        "model_id",
        "prompt_ids",
        "locations",
        "requested_by",
        "requested_at",
        "finished_at",
        "error",
    )
    out = {key: _plain(row.get(key)) for key in keep}
    if out["error"]:
        out["error"] = _reason(out["error"])
    return out


def _plain(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


# -- output ---------------------------------------------------------------


def to_dict(report: CoverageReport) -> dict[str, Any]:
    """The report as JSON-ready data; ``--json`` prints this."""
    names = report.prompt_names
    problems = report.problems()
    return {
        "snapshot": report.snapshot,
        "selection": {
            "models": list(report.selection.models),
            "prompts": [
                {"prompt_id": p, "name": names.get(p)}
                for p in report.selection.prompt_ids
            ],
            "chunker_id": report.selection.chunker_id,
        },
        "sources": [
            {
                "kind": s.kind,
                "ids": s.ids,
                "names": s.names,
                "pdfs": len(s.documents),
                "not_ingested": len(s.not_ingested),
                "not_chunked": len(s.not_chunked),
                "unsupported_files": s.unsupported,
                "unreadable_members": s.unreadable,
                "not_ingested_pdfs": [_doc(d) for d in s.not_ingested],
                "not_chunked_papers": [_doc(d) for d in s.not_chunked],
                "coverage": [
                    {
                        "prompt_id": c.prompt_id,
                        "prompt_name": c.prompt_name,
                        "model_id": c.model_id,
                        "chunks": c.chunks,
                        "succeeded": c.succeeded,
                        "failed_calls": {
                            "total": c.failed_call_count,
                            "by_reason": c.failed_calls,
                        },
                        "invalid_answers": {
                            "total": c.invalid_answer_count,
                            "by_reason": c.invalid_answers,
                        },
                        "not_run": c.not_run,
                    }
                    for c in s.coverage
                ],
            }
            for s in report.sources
        ],
        "failures": [
            {
                "prompt_id": f.prompt_id,
                "prompt_name": names.get(f.prompt_id),
                "model_id": f.model_id,
                "kind": f.state,
                "reason": _reason(f.reason),
                "count": f.count,
            }
            for f in report.failures
        ],
        "prompt_versions": [
            {
                "prompt_id": v.prompt_id,
                "name": v.name,
                "declared": v.prompt_id in report.declared_prompt_ids,
                "current": v.prompt_id in report.current_prompt_ids,
                "extractions": v.extractions,
                "succeeded": v.succeeded,
            }
            for v in report.prompt_versions
        ],
        "undeclared_prompts": report.undeclared_prompts,
        "run_requests": {
            "by_status": report.run_requests_by_status,
            "not_succeeded": report.unfinished_requests,
        },
        "projection_backlog": {
            b.target: {"outstanding": b.outstanding, "selected": b.selected}
            for b in report.backlog
        },
        "relation_check": {
            "examined": report.relation_check.examined,
            "rejected": report.relation_check.rejected,
            "rejected_selected": report.relation_check.rejected_selected,
            "sample_errors": report.relation_check.sample_errors,
        },
        "strict": {"passed": not problems, "problems": problems},
    }


def _doc(document: Document) -> dict[str, Any]:
    return {"path": document.path, "paper_id": document.paper_id, "pmid": document.pmid}


def render_text(report: CoverageReport) -> str:
    """The report for a person to read."""
    names = report.prompt_names
    lines = [
        f"Ingestion coverage at dataset snapshot {report.snapshot}",
        f"  models:  {', '.join(report.selection.models)}",
        f"  chunker: {report.selection.chunker_id}",
        "  prompts: "
        + ", ".join(
            f"{names.get(p) or '?'} ({p})" for p in report.selection.prompt_ids
        ),
    ]
    for source in report.sources:
        lines += ["", f"== {source.kind}: {source.label}"]
        if len(source.ids) > 1 or source.kind != EVERYTHING:
            lines.append(f"   ids: {', '.join(source.ids)}")
        lines.append(
            f"   PDFs {len(source.documents)}, not ingested {len(source.not_ingested)}, "
            f"ingested but not chunked {len(source.not_chunked)}"
            + (
                f", unsupported files {source.unsupported}"
                if source.unsupported
                else ""
            )
        )
        for member, reason in source.unreadable.items():
            lines.append(f"   ! member {member} could not be read: {reason}")
        for doc in source.not_ingested:
            lines.append(
                f"   not ingested: {doc.path}"
                + (f" (PMID {doc.pmid})" if doc.pmid else "")
            )
        for doc in source.not_chunked:
            lines.append(f"   not chunked:  {doc.path}")
        lines.append(
            f"   {'prompt':<28} {'model':<28} {'chunks':>7} {'ok':>7} "
            f"{'failed':>7} {'invalid':>7} {'not run':>7}"
        )
        for c in source.coverage:
            lines.append(
                f"   {(c.prompt_name or c.prompt_id)[:28]:<28} {c.model_id[:28]:<28} "
                f"{c.chunks:>7} {c.succeeded:>7} {c.failed_call_count:>7} "
                f"{c.invalid_answer_count:>7} {c.not_run:>7}"
            )
            for label, reasons in (
                ("failed call", c.failed_calls),
                ("invalid answer", c.invalid_answers),
            ):
                for reason, count in sorted(reasons.items(), key=lambda r: -r[1]):
                    lines.append(f"      {label} ×{count}: {reason}")

    lines += ["", "== Failures, every prompt version and model"]
    if not report.failures:
        lines.append("   none")
    for f in report.failures:
        kind = "failed call" if f.state == FAILED_CALL else "invalid answer"
        lines.append(
            f"   {f.count:>7}  {names.get(f.prompt_id) or '?'} ({f.prompt_id}) × "
            f"{f.model_id}, {kind}: {_reason(f.reason)}"
        )

    lines += ["", "== Prompt versions"]
    for v in report.prompt_versions:
        state = (
            "current"
            if v.prompt_id in report.current_prompt_ids
            else "earlier version"
            if v.prompt_id in report.declared_prompt_ids
            else "not declared"
        )
        lines.append(
            f"   {v.name or '?':<26} {v.prompt_id:<42} {v.extractions:>7} "
            f"extractions ({v.succeeded} succeeded), {state}"
        )
    lines.append(
        "   undeclared prompt names: "
        + (", ".join(report.undeclared_prompts) or "none")
    )

    lines += ["", "== Run requests"]
    lines.append(
        "   "
        + (
            ", ".join(
                f"{k} {v}" for k, v in sorted(report.run_requests_by_status.items())
            )
            or "none"
        )
    )
    for r in report.unfinished_requests:
        lines.append(
            f"   {r['status']}: {r['request_id']} {r['model_id']} "
            f"by {r['requested_by'] or '?'} at {r['requested_at']}"
            + (f": {r['error']}" if r["error"] else "")
        )

    lines += ["", "== Projection backlog (outstanding overall / within the selection)"]
    for b in report.backlog:
        lines.append(f"   {b.target:<28} {b.outstanding:>7} / {b.selected}")
    check = report.relation_check
    if check.examined:
        lines.append(
            f"   of {check.examined} outstanding relation items, {check.rejected} "
            f"({check.rejected_selected} within the selection) are rejected by the "
            "relation contract: they stay outstanding and do not fail --strict"
        )
        for item, error in list(check.sample_errors.items())[:5]:
            lines.append(f"      {item}: {_reason(error)}")

    problems = report.problems()
    lines += ["", f"== Strict check: {'passed' if not problems else 'FAILED'}"]
    lines += [f"   {p}" for p in problems]
    return "\n".join(lines) + "\n"
