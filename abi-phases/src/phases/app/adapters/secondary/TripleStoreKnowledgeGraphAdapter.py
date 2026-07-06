"""Knowledge-graph adapter backed by the engine's triple store (SPARQL).

Implements the join-on-read strategy: extracted items live in the
``extractions`` named graph and carry ``extracted_from_chunk`` links into the
``papers`` named graph, where the source paper path and chunk position live.
Both keyword search and semantic-result enrichment resolve provenance with a
single cross-graph SPARQL query.
"""

from __future__ import annotations

import rdflib
from naas_abi_core import logger
from naas_abi_core.services.triple_store.TripleStoreService import TripleStoreService

from phases.app.interfaces import IKnowledgeGraphPort
from phases.app.models import ItemLocation

PHASES_DOC = "http://purl.obolibrary.org/obo/phases/documents.owl#"
PAPERS_GRAPH = "http://ontology.naas.ai/graph/phases/papers"
EXTRACTIONS_GRAPH = "http://ontology.naas.ai/graph/phases/extractions"

# Selected once and reused so positional unpacking stays in sync everywhere.
_PROVENANCE_VARS = "?id ?text ?pipeline ?model ?chunk_id ?chunk_number ?chunk_text ?path"


def _provenance_body(extra: str) -> str:
    """The shared WHERE body, with ``extra`` extra patterns spliced into the
    extractions graph block (e.g. a ``VALUES ?id`` clause or keyword FILTERs)."""
    return f"""
    GRAPH <{EXTRACTIONS_GRAPH}> {{
        ?item a phases-doc:ExtractedItem ;
            phases-doc:extracted_item_id ?id ;
            phases-doc:extracted_text ?text ;
            phases-doc:extracted_by ?extraction ;
            phases-doc:extracted_from_chunk ?chunk .
        ?extraction phases-doc:pipeline_name ?pipeline .
        OPTIONAL {{ ?extraction phases-doc:model_name ?model . }}
{extra}
    }}
    OPTIONAL {{
        GRAPH <{PAPERS_GRAPH}> {{
            ?chunk phases-doc:chunk_id ?chunk_id ;
                phases-doc:chunk_number ?chunk_number ;
                phases-doc:text ?chunk_text ;
                phases-doc:chunk_of ?paper .
            ?paper phases-doc:path ?path .
        }}
    }}
"""


def _str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


class TripleStoreKnowledgeGraphAdapter(IKnowledgeGraphPort):
    def __init__(self, triple_store: TripleStoreService):
        self._triple_store = triple_store

    # -- query helpers ----------------------------------------------------

    @staticmethod
    def _pipeline_values_clause(pipelines: list[str] | None) -> str:
        if not pipelines:
            return ""
        values = " ".join(rdflib.Literal(p).n3() for p in pipelines)
        return f"        VALUES ?pipeline {{ {values} }}"

    @staticmethod
    def _row_to_location(
        pipeline, model, chunk_id, chunk_number, chunk_text, path
    ) -> ItemLocation:
        return ItemLocation(
            pipeline=_str(pipeline),
            model=_str(model),
            chunk_id=_str(chunk_id),
            chunk_number=_int(chunk_number),
            chunk_text=_str(chunk_text),
            paper_path=_str(path),
        )

    def _run(self, query: str):
        try:
            return list(self._triple_store.query(query))
        except Exception as exc:
            logger.error(f"Knowledge-graph query failed: {exc}")
            return []

    # -- ports ------------------------------------------------------------

    def resolve_locations(self, item_ids: list[str]) -> dict[str, ItemLocation]:
        unique_ids = list(dict.fromkeys(i for i in item_ids if i))
        if not unique_ids:
            return {}

        values = " ".join(rdflib.Literal(i).n3() for i in unique_ids)
        body = _provenance_body(f"        VALUES ?id {{ {values} }}")
        query = (
            f"PREFIX phases-doc: <{PHASES_DOC}>\n"
            f"SELECT {_PROVENANCE_VARS} WHERE {{{body}}}"
        )

        locations: dict[str, ItemLocation] = {}
        for row in self._run(query):
            (
                item_id,
                _text,
                pipeline,
                model,
                chunk_id,
                chunk_number,
                chunk_text,
                path,
            ) = tuple(row)
            key = _str(item_id)
            if key is None:
                continue
            locations[key] = self._row_to_location(
                pipeline, model, chunk_id, chunk_number, chunk_text, path
            )
        return locations

    def keyword_search(
        self,
        tokens: list[str],
        pipelines: list[str] | None,
        limit: int,
    ) -> list[tuple[str, str, ItemLocation]]:
        if not tokens:
            return []

        filters = "\n".join(
            f"        FILTER(CONTAINS(LCASE(?text), {rdflib.Literal(token).n3()}))"
            for token in tokens
        )
        extra = self._pipeline_values_clause(pipelines)
        extra = f"{extra}\n{filters}" if extra else filters
        body = _provenance_body(extra)
        query = (
            f"PREFIX phases-doc: <{PHASES_DOC}>\n"
            f"SELECT {_PROVENANCE_VARS} WHERE {{{body}}}\n"
            f"ORDER BY ?path ?chunk_number\nLIMIT {int(limit)}"
        )

        hits: list[tuple[str, str, ItemLocation]] = []
        for row in self._run(query):
            (
                item_id,
                text,
                pipeline,
                model,
                chunk_id,
                chunk_number,
                chunk_text,
                path,
            ) = tuple(row)
            key = _str(item_id)
            if key is None:
                continue
            hits.append(
                (
                    key,
                    _str(text) or "",
                    self._row_to_location(
                        pipeline, model, chunk_id, chunk_number, chunk_text, path
                    ),
                )
            )
        return hits

    def list_pipelines(self) -> list[str]:
        query = (
            f"PREFIX phases-doc: <{PHASES_DOC}>\n"
            "SELECT DISTINCT ?pipeline WHERE {\n"
            f"    GRAPH <{EXTRACTIONS_GRAPH}> {{\n"
            "        ?e a phases-doc:Extraction ; phases-doc:pipeline_name ?pipeline .\n"
            "    }\n}\nORDER BY ?pipeline"
        )
        pipelines: list[str] = []
        for row in self._run(query):
            value = _str(tuple(row)[0])
            if value:
                pipelines.append(value)
        return pipelines
