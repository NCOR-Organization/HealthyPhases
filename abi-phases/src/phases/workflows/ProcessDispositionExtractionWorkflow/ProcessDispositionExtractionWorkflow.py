"""Probability-modulating process-disposition extraction workflow.

Purpose
-------
Extract, from each document chunk, claims of the form

    "<subject> increases (or decreases / has no effect on) the probability
     that <target> happens"

and persist them in BFO terms:

    - A `bfo:Process` (subject_process) with a `bfo:has_participant`
      pointing at an `bfo:IndependentContinuant` (subject_participant).
    - A `phases-rel:ProbabilityModulatingDisposition` (one of the
      Increase / Decrease / NoEffect subclasses) `bfo:inheres_in` the
      participant.
    - The subject process `bfo:realizes` that disposition.
    - The disposition `phases-rel:disposition_target_process` points at
      another `bfo:Process` (target_process).
    - Every minted entity carries `phases-doc:extracted_from_chunk` and
      `phases-doc:extracted_by` so provenance is queryable; the
      enclosing `phases-doc:Extraction` records the prompt + model.
    - When the participant or target text matches an existing
      `phases-label:ExtractedLabel` (by normalized text), a
      `phases-rel:linked_to_label` edge is added.

Idempotency
-----------
Chunks already processed by an `Extraction` with the same
`(prompt_hash, model_name)` are skipped, mirroring
`GenericChunkExtractionWorkflow`.

CLI
---
See `run_extraction.py` in this folder.
"""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import cast

from fastapi import APIRouter
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from naas_abi_core import logger
from naas_abi_core.workflow.workflow import (
    Workflow,
    WorkflowConfiguration,
    WorkflowParameters,
)
import rdflib
from rdflib.term import Node

from phases import ABIModule

try:
    from tqdm import tqdm
except Exception:
    tqdm = None


# ---------------------------------------------------------------------------
# Namespaces and graphs
# ---------------------------------------------------------------------------

BFO = rdflib.Namespace("http://purl.obolibrary.org/obo/")
PHASES_DOC = rdflib.Namespace("http://purl.obolibrary.org/obo/phases/documents.owl#")
PHASES_REL = rdflib.Namespace("http://purl.obolibrary.org/obo/phases/relations.owl#")
PHASES_LABEL = rdflib.Namespace("http://purl.obolibrary.org/obo/phases/labels.owl#")

# BFO URIs we reuse directly.
BFO_PROCESS = BFO["BFO_0000015"]
BFO_INDEPENDENT_CONTINUANT = BFO["BFO_0000004"]
BFO_HAS_PARTICIPANT = BFO["BFO_0000057"]
BFO_REALIZES = BFO["BFO_0000055"]
BFO_INHERES_IN = BFO["BFO_0000197"]

# Direction → disposition class.
DIRECTION_TO_CLASS = {
    "increases": PHASES_REL["IncreaseProbabilityDisposition"],
    "decreases": PHASES_REL["DecreaseProbabilityDisposition"],
    "no-effect": PHASES_REL["NoEffectProbabilityDisposition"],
}
VALID_DIRECTIONS = set(DIRECTION_TO_CLASS)

PAPERS_GRAPH = rdflib.URIRef("http://ontology.naas.ai/graph/phases/papers")
EXTRACTIONS_GRAPH = rdflib.URIRef(
    "http://ontology.naas.ai/graph/phases/extractions"
)


# ---------------------------------------------------------------------------
# Configuration / parameters
# ---------------------------------------------------------------------------


@dataclass
class ProcessDispositionExtractionWorkflowConfiguration(WorkflowConfiguration):
    prompt_template: str = ""  # required: must contain `{chunk_text}`
    model_name: str = "gpt-5-mini"
    model_timeout_seconds: int = 60
    model_max_retries: int = 1
    extraction_workers: int = 10
    max_relations_per_chunk: int | None = 8
    pipeline_name: str = "process_dispositions"
    # When True, look up existing ExtractedLabel by normalized text and
    # attach `linked_to_label` edges. Set False for a dry run that
    # doesn't touch the labels graph.
    link_to_labels: bool = True


class ProcessDispositionExtractionWorkflowParameters(WorkflowParameters):
    paths: list[str] | None = None
    chunk_limit: int | None = None
    workers: int | None = None
    output_path: str | None = None
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


class ProcessDispositionExtractionWorkflow(
    Workflow[ProcessDispositionExtractionWorkflowParameters]
):
    module: ABIModule
    _configuration: ProcessDispositionExtractionWorkflowConfiguration

    def __init__(
        self, configuration: ProcessDispositionExtractionWorkflowConfiguration
    ):
        super().__init__(configuration)
        self._configuration = configuration
        self.module = ABIModule.get_instance()
        if "{chunk_text}" not in configuration.prompt_template:
            raise ValueError(
                "prompt_template must contain the '{chunk_text}' placeholder"
            )
        self._chat_model = ChatOpenAI(
            model=configuration.model_name,
            temperature=0,
            timeout=configuration.model_timeout_seconds,
            max_retries=configuration.model_max_retries,
        )

    # -- identity ------------------------------------------------------------

    def _extraction_id(self) -> tuple[str, str, rdflib.URIRef]:
        cfg = self._configuration
        prompt_hash = hashlib.sha256(cfg.prompt_template.encode()).hexdigest()
        extraction_id = f"{cfg.model_name}:{cfg.pipeline_name}:{prompt_hash[:16]}"
        return (
            extraction_id,
            prompt_hash,
            rdflib.URIRef(f"urn:phases:extraction:{extraction_id}"),
        )

    # -- candidate chunks ----------------------------------------------------

    def _build_candidates_query(
        self, parameters: ProcessDispositionExtractionWorkflowParameters
    ) -> str:
        path_clause = ""
        if parameters.paths:
            values = " ".join(
                rdflib.Literal(path).n3() for path in parameters.paths
            )
            path_clause = f"VALUES ?path {{ {values} }}"

        limit = parameters.chunk_limit
        limit_clause = f"LIMIT {limit}" if limit is not None else ""

        _, prompt_hash, _ = self._extraction_id()
        prompt_hash_lit = rdflib.Literal(prompt_hash).n3()
        model_name_lit = rdflib.Literal(self._configuration.model_name).n3()

        return f"""PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>

SELECT ?chunk ?chunk_id ?text ?path WHERE {{
    GRAPH <{PAPERS_GRAPH}> {{
        ?chunk a phases-doc:Chunk ;
            phases-doc:chunk_id ?chunk_id ;
            phases-doc:text ?text ;
            phases-doc:chunk_of ?pdf_paper_file .
        ?pdf_paper_file phases-doc:path ?path .
        {path_clause}
    }}
    # Skip chunks already processed by an Extraction with the same prompt + model.
    FILTER NOT EXISTS {{
        GRAPH <{EXTRACTIONS_GRAPH}> {{
            ?prior_extraction phases-doc:prompt_hash {prompt_hash_lit} ;
                              phases-doc:model_name {model_name_lit} .
            ?prior_entity phases-doc:extracted_by ?prior_extraction ;
                          phases-doc:extracted_from_chunk ?chunk .
        }}
    }}
}}
ORDER BY ?chunk_id
{limit_clause}"""

    def _load_candidate_chunks(
        self, parameters: ProcessDispositionExtractionWorkflowParameters
    ) -> list[tuple[Node, str, str, str]]:
        rows = self.module.engine.services.triple_store.query(
            self._build_candidates_query(parameters)
        )
        parsed: list[tuple[Node, str, str, str]] = []
        for row in rows:
            if isinstance(row, bool):
                continue
            try:
                items = tuple(row)
            except TypeError:
                continue
            if len(items) != 4:
                continue
            chunk, chunk_id, text, path = items
            parsed.append(
                (cast(Node, chunk), str(chunk_id), str(text), str(path))
            )
        return parsed

    # -- LLM call + response parsing -----------------------------------------

    def _build_prompt(self, chunk_text: str) -> str:
        return self._configuration.prompt_template.format(chunk_text=chunk_text)

    @staticmethod
    def _normalize_phrase(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text.strip())
        return cleaned

    def _parse_response(self, response_text: str) -> list[dict]:
        payload: dict | None = None
        try:
            parsed = json.loads(response_text)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", response_text, flags=re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict):
                        payload = parsed
                except json.JSONDecodeError:
                    payload = None

        raw_items = payload.get("relations", []) if payload else []
        if not isinstance(raw_items, list):
            return []

        cleaned: list[dict] = []
        seen: set[tuple[str, str, str, str]] = set()
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            subject_process = self._normalize_phrase(
                str(item.get("subject_process", ""))
            )
            subject_participant = self._normalize_phrase(
                str(item.get("subject_participant", ""))
            )
            target_process = self._normalize_phrase(
                str(item.get("target_process", ""))
            )
            direction = str(item.get("direction", "")).strip().lower()
            evidence_text = self._normalize_phrase(
                str(item.get("evidence_text", ""))
            )

            if not (subject_process and subject_participant and target_process):
                continue
            if direction not in VALID_DIRECTIONS:
                continue

            key = (
                subject_process.lower(),
                subject_participant.lower(),
                target_process.lower(),
                direction,
            )
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(
                {
                    "subject_process": subject_process,
                    "subject_participant": subject_participant,
                    "target_process": target_process,
                    "direction": direction,
                    "evidence_text": evidence_text,
                }
            )

        max_n = self._configuration.max_relations_per_chunk
        if max_n is not None:
            cleaned = cleaned[:max_n]
        return cleaned

    def _extract(self, chunk_text: str) -> list[dict]:
        prompt = self._build_prompt(chunk_text)
        response: AIMessage = cast(AIMessage, self._chat_model.invoke(prompt))
        content = response.content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            response_text = "\n".join(parts)
        else:
            response_text = str(content)
        return self._parse_response(response_text)

    def _extract_for_chunk(
        self, chunk: tuple[Node, str, str, str]
    ) -> tuple[str, str, list[dict], str | None]:
        _, chunk_id, text, path = chunk
        try:
            return chunk_id, path, self._extract(text), None
        except Exception as exc:
            return chunk_id, path, [], str(exc)

    # -- run -----------------------------------------------------------------

    def run(
        self, parameters: ProcessDispositionExtractionWorkflowParameters
    ) -> dict[str, list[dict]]:
        chunks = self._load_candidate_chunks(parameters)
        logger.debug(
            f"ProcessDispositionExtraction candidate chunks: {len(chunks)}"
        )

        if parameters.dry_run:
            if not chunks:
                print(
                    "[ProcessDispositionExtraction][dry-run] No candidate chunks.",
                    flush=True,
                )
                return {}
            chunk_id, path, items, error = self._extract_for_chunk(chunks[0])
            print(f"[dry-run] Chunk ID: {chunk_id}", flush=True)
            print(f"[dry-run] Source path: {path}", flush=True)
            if error:
                print(f"[dry-run] Error: {error}", flush=True)
            else:
                print(f"[dry-run] {len(items)} relations extracted:", flush=True)
                for i, it in enumerate(items, 1):
                    print(
                        f"  {i}. ({it['direction']}) "
                        f"{it['subject_process']} "
                        f"[participant: {it['subject_participant']}] "
                        f"-> {it['target_process']}",
                        flush=True,
                    )
            return {chunk_id: items}

        workers = parameters.workers or self._configuration.extraction_workers
        workers = max(1, workers)

        results: dict[str, list[dict]] = {}
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(self._extract_for_chunk, c) for c in chunks
                ]
                completion = as_completed(futures)
                if tqdm is not None:
                    completion = tqdm(
                        completion,
                        total=len(futures),
                        desc="Extracting",
                        unit="chunk",
                    )
                for future in completion:
                    chunk_id, path, items, error = future.result()
                    if error:
                        logger.error(f"Chunk {chunk_id} ({path}) failed: {error}")
                        continue
                    results[chunk_id] = items
        else:
            chunk_iter = chunks
            if tqdm is not None:
                chunk_iter = tqdm(chunks, desc="Extracting", unit="chunk")
            for chunk in chunk_iter:
                chunk_id, path, items, error = self._extract_for_chunk(chunk)
                if error:
                    logger.error(f"Chunk {chunk_id} ({path}) failed: {error}")
                    continue
                results[chunk_id] = items

        if parameters.output_path:
            Path(parameters.output_path).write_text(json.dumps(results, indent=2))
            logger.debug(f"Wrote results to {parameters.output_path}")

        self._persist_to_triple_store(results)
        return results

    # -- persistence ---------------------------------------------------------

    def _persist_to_triple_store(self, results: dict[str, list[dict]]) -> None:
        if not results:
            return

        cfg = self._configuration
        extraction_id, prompt_hash, extraction_uri = self._extraction_id()

        graph = rdflib.Graph()

        # Extraction provenance.
        graph.add((extraction_uri, rdflib.RDF.type, PHASES_DOC.Extraction))
        graph.add(
            (extraction_uri, PHASES_DOC.extraction_id, rdflib.Literal(extraction_id))
        )
        graph.add(
            (
                extraction_uri,
                PHASES_DOC.pipeline_name,
                rdflib.Literal(cfg.pipeline_name),
            )
        )
        graph.add(
            (
                extraction_uri,
                PHASES_DOC.prompt_template,
                rdflib.Literal(cfg.prompt_template),
            )
        )
        graph.add(
            (extraction_uri, PHASES_DOC.prompt_hash, rdflib.Literal(prompt_hash))
        )
        graph.add(
            (extraction_uri, PHASES_DOC.model_name, rdflib.Literal(cfg.model_name))
        )

        chunk_uri_by_id = self._resolve_chunk_uris(list(results.keys()))

        # Resolve label canonicals only once across all extracted phrases.
        label_lookup: dict[str, rdflib.URIRef] = {}
        if cfg.link_to_labels:
            phrases: set[str] = set()
            for items in results.values():
                for it in items:
                    phrases.add(it["subject_participant"].lower())
                    phrases.add(it["target_process"].lower())
            label_lookup = self._resolve_label_uris(phrases)

        for chunk_id, items in results.items():
            chunk_uri = chunk_uri_by_id.get(chunk_id)
            if chunk_uri is None:
                logger.warning(
                    f"No Chunk URI found for chunk_id {chunk_id}; skipping its relations."
                )
                continue
            for i, item in enumerate(items):
                self._emit_relation(
                    graph,
                    extraction_id=extraction_id,
                    extraction_uri=extraction_uri,
                    chunk_id=chunk_id,
                    chunk_uri=chunk_uri,
                    index=i,
                    item=item,
                    label_lookup=label_lookup,
                )

        total_relations = sum(len(v) for v in results.values())
        logger.debug(
            f"Inserting process-disposition extraction graph: "
            f"1 Extraction + {total_relations} relation(s)"
        )
        self.module.engine.services.triple_store.insert(
            graph, graph_name=EXTRACTIONS_GRAPH
        )

    def _emit_relation(
        self,
        graph: rdflib.Graph,
        *,
        extraction_id: str,
        extraction_uri: rdflib.URIRef,
        chunk_id: str,
        chunk_uri: rdflib.URIRef,
        index: int,
        item: dict,
        label_lookup: dict[str, rdflib.URIRef],
    ) -> None:
        """Emit the BFO subgraph for one extracted probability-modulating claim."""

        direction = item["direction"]
        disp_class = DIRECTION_TO_CLASS[direction]

        subj_proc = item["subject_process"]
        subj_part = item["subject_participant"]
        tgt_proc = item["target_process"]
        evidence = item.get("evidence_text") or ""

        # Stable, idempotent URIs for the four entities. The hash keys on
        # (extraction_id, chunk_id, role, normalized text) so a rerun with
        # the same prompt/model on the same chunk produces the same URIs.
        def mint(role: str, text: str) -> rdflib.URIRef:
            digest = hashlib.sha256(
                f"{extraction_id}:{chunk_id}:{index}:{role}:{text.lower()}".encode()
            ).hexdigest()
            return rdflib.URIRef(f"urn:phases:proc_disp:{role}:{digest}")

        subj_proc_uri = mint("subject_process", subj_proc)
        subj_part_uri = mint("subject_participant", subj_part)
        disp_uri = mint(f"disposition:{direction}", f"{subj_part}|{tgt_proc}")
        tgt_proc_uri = mint("target_process", tgt_proc)

        # Subject process (bfo:Process).
        graph.add((subj_proc_uri, rdflib.RDF.type, BFO_PROCESS))
        graph.add((subj_proc_uri, rdflib.RDFS.label, rdflib.Literal(subj_proc)))
        graph.add((subj_proc_uri, BFO_HAS_PARTICIPANT, subj_part_uri))
        graph.add((subj_proc_uri, BFO_REALIZES, disp_uri))
        self._attach_provenance(
            graph, subj_proc_uri, chunk_uri, extraction_uri, evidence
        )

        # Subject participant (bfo:IndependentContinuant).
        graph.add(
            (subj_part_uri, rdflib.RDF.type, BFO_INDEPENDENT_CONTINUANT)
        )
        graph.add((subj_part_uri, rdflib.RDFS.label, rdflib.Literal(subj_part)))
        self._attach_provenance(
            graph, subj_part_uri, chunk_uri, extraction_uri, evidence=None
        )

        # Disposition (one of the three subclasses).
        graph.add((disp_uri, rdflib.RDF.type, disp_class))
        graph.add(
            (
                disp_uri,
                rdflib.RDFS.label,
                rdflib.Literal(f"{direction} probability of {tgt_proc}"),
            )
        )
        graph.add((disp_uri, BFO_INHERES_IN, subj_part_uri))
        graph.add(
            (disp_uri, PHASES_REL.disposition_target_process, tgt_proc_uri)
        )
        self._attach_provenance(
            graph, disp_uri, chunk_uri, extraction_uri, evidence=None
        )

        # Target process (bfo:Process).
        graph.add((tgt_proc_uri, rdflib.RDF.type, BFO_PROCESS))
        graph.add((tgt_proc_uri, rdflib.RDFS.label, rdflib.Literal(tgt_proc)))
        self._attach_provenance(
            graph, tgt_proc_uri, chunk_uri, extraction_uri, evidence=None
        )

        # Optional label-canonicalisation edges.
        participant_label = label_lookup.get(subj_part.lower())
        if participant_label is not None:
            graph.add((subj_part_uri, PHASES_REL.linked_to_label, participant_label))
        target_label = label_lookup.get(tgt_proc.lower())
        if target_label is not None:
            graph.add((tgt_proc_uri, PHASES_REL.linked_to_label, target_label))

    @staticmethod
    def _attach_provenance(
        graph: rdflib.Graph,
        entity_uri: rdflib.URIRef,
        chunk_uri: rdflib.URIRef,
        extraction_uri: rdflib.URIRef,
        evidence: str | None,
    ) -> None:
        graph.add((entity_uri, PHASES_DOC.extracted_from_chunk, chunk_uri))
        graph.add((entity_uri, PHASES_DOC.extracted_by, extraction_uri))
        if evidence:
            graph.add(
                (entity_uri, PHASES_REL.evidence_text, rdflib.Literal(evidence))
            )

    # -- helpers -------------------------------------------------------------

    def _resolve_chunk_uris(self, chunk_ids: list[str]) -> dict[str, rdflib.URIRef]:
        if not chunk_ids:
            return {}
        values = " ".join(rdflib.Literal(cid).n3() for cid in chunk_ids)
        query = f"""PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>
SELECT ?chunk ?chunk_id WHERE {{
    GRAPH <{PAPERS_GRAPH}> {{
        ?chunk a phases-doc:Chunk ; phases-doc:chunk_id ?chunk_id .
        VALUES ?chunk_id {{ {values} }}
    }}
}}"""
        rows = self.module.engine.services.triple_store.query(query)
        return {
            str(chunk_id): cast(rdflib.URIRef, chunk) for chunk, chunk_id in rows
        }

    def _resolve_label_uris(
        self, normalized_phrases: set[str]
    ) -> dict[str, rdflib.URIRef]:
        """Map lower-cased phrase → ExtractedLabel URI when present.

        Matches by case-insensitive equality of `phases-label:label_text`.
        """
        if not normalized_phrases:
            return {}
        values = " ".join(
            rdflib.Literal(p).n3() for p in normalized_phrases
        )
        query = f"""PREFIX phases-label: <http://purl.obolibrary.org/obo/phases/labels.owl#>
SELECT ?label ?label_text_lc WHERE {{
    ?label a phases-label:ExtractedLabel ;
           phases-label:label_text ?label_text .
    BIND(LCASE(STR(?label_text)) AS ?label_text_lc)
    VALUES ?label_text_lc {{ {values} }}
}}"""
        try:
            rows = self.module.engine.services.triple_store.query(query)
        except Exception as exc:
            logger.warning(f"Label lookup failed; skipping label linking: {exc}")
            return {}

        lookup: dict[str, rdflib.URIRef] = {}
        for row in rows:
            if isinstance(row, bool):
                continue
            try:
                label_uri, label_text_lc = tuple(row)
            except (TypeError, ValueError):
                continue
            lookup.setdefault(str(label_text_lc), cast(rdflib.URIRef, label_uri))
        return lookup

    # -- adapters required by the Workflow ABC -------------------------------

    def as_tools(self) -> list[BaseTool]:
        return []

    def as_api(
        self,
        router: APIRouter,
        route_name: str = "",
        name: str = "",
        description: str = "",
        description_stream: str = "",
        tags: list[str | Enum] | None = [],
    ) -> None:
        return None
