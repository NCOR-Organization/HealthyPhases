"""An in-memory :class:`~phases_v2.coverage.interfaces.CoverageReader`.

It counts the way the dataset adapter's SQL does, from plain rows, so domain
tests describe a corpus rather than a query. It has no method that writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from phases_v2.coverage.interfaces import (
    FAILED_CALL,
    GRAPH,
    INVALID_ANSWER,
    NOT_RUN,
    RELATIONS,
    SUCCEEDED,
    VECTOR_CHUNKS,
    VECTOR_ITEMS,
    Backlog,
    Collection,
    CoverageCount,
    FailureCount,
    PromptVersion,
    RelationCheck,
    SavedSearch,
    Selection,
)
from phases_v2.paper_collections.fakes import FakeMemberSources
from phases_v2.paper_collections.interfaces import Artifact


def _state(extraction: dict[str, Any] | None) -> str:
    if extraction is None:
        return NOT_RUN
    if extraction["status"] == SUCCEEDED:
        return SUCCEEDED
    return (
        INVALID_ANSWER
        if (extraction.get("raw_response") or "").strip()
        else FAILED_CALL
    )


@dataclass
class FakeCoverageReader:
    sources: FakeMemberSources = field(default_factory=FakeMemberSources)
    collection_rows: list[Collection] = field(default_factory=list)
    searches: list[SavedSearch] = field(default_factory=list)
    downloaded: list[Artifact] = field(default_factory=list)
    #: paper id → where it was first read from.
    papers: dict[str, Artifact] = field(default_factory=dict)
    #: ``{chunk_id, paper_id, chunker_id}``
    chunks: list[dict[str, Any]] = field(default_factory=list)
    #: prompt id → (name, output key)
    prompts: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: ``{chunk_id, model_id, prompt_id, status, raw_response, error}``; the
    #: extraction id is derived as the real one is, from the first three.
    extractions: list[dict[str, Any]] = field(default_factory=list)
    #: ``{item_id, extraction_id, prompt_id}``
    items: list[dict[str, Any]] = field(default_factory=list)
    projected: set[tuple[str, str]] = field(default_factory=set)
    requests: list[dict[str, Any]] = field(default_factory=list)
    #: item id → why the relation contract rejects it.
    rejected_relations: dict[str, str] = field(default_factory=dict)
    version: int = 7

    # -- helpers for tests ----------------------------------------------

    @staticmethod
    def extraction_id(row: dict[str, Any]) -> str:
        return row.get("extraction_id") or (
            f"{row['chunk_id']}:{row['model_id']}:{row['prompt_id']}"
        )

    def _extraction(self, chunk_id: str, model_id: str, prompt_id: str):
        for row in self.extractions:
            if (row["chunk_id"], row["model_id"], row["prompt_id"]) == (
                chunk_id,
                model_id,
                prompt_id,
            ):
                return row
        return None

    # -- CoverageReader -------------------------------------------------

    def snapshot(self):
        return self.version

    def collections(self):
        return list(self.collection_rows)

    def saved_searches(self):
        return [s for s in self.searches if self.sources.pubmed_query(s.query_id)]

    def member_sources(self):
        return self.sources

    def supported(self, file_name):
        return file_name.lower().endswith(".pdf")

    def downloaded_pdfs(self):
        return list(self.downloaded)

    def ingested_papers(self):
        return list(self.papers.values())

    def chunked_papers(self, chunker_id):
        return {c["paper_id"] for c in self.chunks if c["chunker_id"] == chunker_id}

    def coverage(self, scopes, selection: Selection):
        counts: dict[tuple, int] = {}
        for scope, paper_ids in scopes.items():
            for chunk in self.chunks:
                if (
                    chunk["paper_id"] not in paper_ids
                    or chunk["chunker_id"] != selection.chunker_id
                ):
                    continue
                for model_id in selection.models:
                    for prompt_id in selection.prompt_ids:
                        row = self._extraction(chunk["chunk_id"], model_id, prompt_id)
                        state = _state(row)
                        reason = (
                            (row.get("error") or "")
                            if state in (FAILED_CALL, INVALID_ANSWER)
                            else None
                        )
                        key = (scope, model_id, prompt_id, state, reason)
                        counts[key] = counts.get(key, 0) + 1
        return [CoverageCount(*key, chunks=n) for key, n in counts.items()]

    def failures(self):
        counts: dict[tuple, int] = {}
        for row in self.extractions:
            state = _state(row)
            if state == SUCCEEDED:
                continue
            key = (row["prompt_id"], row["model_id"], state, row.get("error") or "")
            counts[key] = counts.get(key, 0) + 1
        return [FailureCount(*key, count=n) for key, n in counts.items()]

    def prompt_versions(self):
        ids = set(self.prompts) | {e["prompt_id"] for e in self.extractions}
        return [
            PromptVersion(
                prompt_id=prompt_id,
                name=self.prompts.get(prompt_id, (None, None))[0],
                extractions=sum(e["prompt_id"] == prompt_id for e in self.extractions),
                succeeded=sum(
                    e["prompt_id"] == prompt_id and e["status"] == SUCCEEDED
                    for e in self.extractions
                ),
            )
            for prompt_id in sorted(ids)
        ]

    def run_requests(self):
        return list(self.requests)

    def projection_backlog(self, selection: Selection):
        chunker = {c["chunk_id"]: c["chunker_id"] for c in self.chunks}
        succeeded = {
            self.extraction_id(e): e
            for e in self.extractions
            if e["status"] == SUCCEEDED
        }

        def chosen(extraction):
            return (
                extraction["model_id"] in selection.models
                and extraction["prompt_id"] in selection.prompt_ids
                and chunker.get(extraction["chunk_id"]) == selection.chunker_id
            )

        def backlog(target, keyed):
            pending = [
                (k, sel) for k, sel in keyed if (target, k) not in self.projected
            ]
            return Backlog(target, len(pending), sum(sel for _, sel in pending))

        items = [i for i in self.items if i["extraction_id"] in succeeded]
        return [
            backlog(GRAPH, [(k, chosen(e)) for k, e in succeeded.items()]),
            backlog(
                VECTOR_CHUNKS,
                [
                    (c["chunk_id"], c["chunker_id"] == selection.chunker_id)
                    for c in self.chunks
                ],
            ),
            backlog(
                VECTOR_ITEMS,
                [(i["item_id"], chosen(succeeded[i["extraction_id"]])) for i in items],
            ),
            backlog(
                RELATIONS,
                [
                    (i["item_id"], chosen(succeeded[i["extraction_id"]]))
                    for i in items
                    if self.prompts.get(i["prompt_id"], ("", ""))[1] == "relations"
                ],
            ),
        ]

    def relation_check(self, selection: Selection):
        succeeded = {
            self.extraction_id(e): e
            for e in self.extractions
            if e["status"] == SUCCEEDED
        }
        chunker = {c["chunk_id"]: c["chunker_id"] for c in self.chunks}
        outstanding = [
            i
            for i in self.items
            if i["extraction_id"] in succeeded
            and self.prompts.get(i["prompt_id"], ("", ""))[1] == "relations"
            and (RELATIONS, i["item_id"]) not in self.projected
        ]
        rejected = [i for i in outstanding if i["item_id"] in self.rejected_relations]

        def chosen(item):
            e = succeeded[item["extraction_id"]]
            return (
                e["model_id"] in selection.models
                and e["prompt_id"] in selection.prompt_ids
                and chunker.get(e["chunk_id"]) == selection.chunker_id
            )

        return RelationCheck(
            examined=len(outstanding),
            rejected=len(rejected),
            rejected_selected=sum(chosen(i) for i in rejected),
            sample_errors={
                i["item_id"]: self.rejected_relations[i["item_id"]] for i in rejected
            },
        )
