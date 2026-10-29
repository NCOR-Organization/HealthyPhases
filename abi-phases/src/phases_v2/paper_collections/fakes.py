"""In-memory :class:`~phases_v2.paper_collections.interfaces.MemberSources`."""

from __future__ import annotations

from dataclasses import dataclass, field

from phases_v2.paper_collections.interfaces import Artifact, MemberUnavailable


@dataclass
class FakeMemberSources:
    #: prefix -> objects beneath it (keys relative to the prefix).
    folders: dict[str, list[Artifact]] = field(default_factory=dict)
    #: query_id -> currently published artifacts; mutate to publish more.
    queries: dict[str, list[Artifact]] = field(default_factory=dict)
    pmids: dict[str, list[Artifact]] = field(default_factory=dict)
    ingested: dict[str, Artifact] = field(default_factory=dict)
    unreachable: set[str] = field(default_factory=set)

    def folder(self, prefix):
        if prefix in self.unreachable:
            raise MemberUnavailable(f"Could not read {prefix}")
        return list(self.folders.get(prefix, []))

    def pubmed_query(self, query_id):
        return list(self.queries.get(query_id, []))

    def pubmed_paper(self, pmid):
        return list(self.pmids.get(pmid, []))

    def ingested_paper(self, paper_id):
        return self.ingested.get(paper_id)

    def paper_ids_by_path(self, paths):
        by_path = {a.path: paper_id for paper_id, a in self.ingested.items()}
        return {path: by_path[path] for path in paths if path in by_path}
