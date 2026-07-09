"""Infer directed concept emergence from labels and axioms.

Purpose
- Load labels and axioms from the knowledge graph using SPARQL.
- Compute label-to-label associations from chunk co-occurrence.
- Add directionality evidence from axiom phrasing (if/then, leads to, predicts, etc.).
- Produce confidence and exclusivity scores for edges A -> B.
- Optionally persist inferred relations to the triple store.

How to run (from `abi/`)
- `uv run abi run script abi_phases/phases/workflows/LabelAxiomEmergenceWorkflow/LabelAxiomEmergenceWorkflow.py`
- `uv run abi run script abi_phases/phases/workflows/LabelAxiomEmergenceWorkflow/LabelAxiomEmergenceWorkflow.py --min-label-occurrence 4 --min-pair-cooccurrence 2`
- `uv run abi run script abi_phases/phases/workflows/LabelAxiomEmergenceWorkflow/LabelAxiomEmergenceWorkflow.py --path ".../paper1.pdf" --path ".../paper2.pdf" --persist-relations`
"""

from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

import rdflib
from fastapi import APIRouter
from langchain_core.tools import BaseTool
from naas_abi_core import logger
from naas_abi_core.workflow.workflow import (
    Workflow,
    WorkflowConfiguration,
    WorkflowParameters,
)

from phases import ABIModule


@dataclass
class LabelObservation:
    label_uri: str
    label_id: str
    label_text: str
    canonical_label: str
    chunk_uri: str
    chunk_id: str
    path: str


@dataclass
class AxiomObservation:
    axiom_uri: str
    axiom_id: str
    axiom_text: str
    chunk_uri: str
    chunk_id: str
    path: str


@dataclass
class RelationEdge:
    source_label: str
    target_label: str
    relation_type: str
    belongs_confidence: float
    exclusive_to_target_confidence: float
    co_occurrence_score: float
    directional_score: float
    stability_score: float
    co_occurrence_count: int
    forward_axiom_votes: int
    reverse_axiom_votes: int
    evidence_paths_count: int
    best_alternative_target: str
    best_alternative_support: float
    support_score: float
    why: str
    supporting_chunk_ids: list[str]
    supporting_axiom_ids: list[str]


class LabelAxiomEmergenceWorkflowConfiguration(WorkflowConfiguration):
    allowed_path_tokens: list[str] = ["solitude", "paid"]
    default_min_label_occurrence: int = 3
    default_min_pair_cooccurrence: int = 2
    default_min_support: float = 0.2
    default_max_edges: int = 500
    co_occurrence_weight: float = 0.45
    directional_weight: float = 0.45
    stability_weight: float = 0.10
    default_output_subdir: str = "outputs/label_axiom_emergence"


class LabelAxiomEmergenceWorkflowParameters(WorkflowParameters):
    output_dir: str | None = None
    paths: list[str] | None = None
    path_tokens: list[str] | None = None
    min_label_occurrence: int | None = None
    min_pair_cooccurrence: int | None = None
    min_support: float | None = None
    max_edges: int | None = None
    persist_relations: bool = False
    dry_run: bool = False


class LabelAxiomEmergenceWorkflow(Workflow[LabelAxiomEmergenceWorkflowParameters]):
    module: ABIModule
    _configuration: LabelAxiomEmergenceWorkflowConfiguration

    def __init__(self, configuration: LabelAxiomEmergenceWorkflowConfiguration):
        super().__init__(configuration)
        self._configuration = configuration
        self.module = ABIModule.get_instance()

    def _effective_path_tokens(
        self, parameters: LabelAxiomEmergenceWorkflowParameters
    ) -> list[str]:
        tokens = parameters.path_tokens or self._configuration.allowed_path_tokens
        return [token.strip().lower() for token in tokens if token.strip()]

    def _effective_output_dir(
        self, parameters: LabelAxiomEmergenceWorkflowParameters
    ) -> Path:
        if parameters.output_dir:
            return Path(parameters.output_dir)
        return (
            Path(__file__).resolve().parent / self._configuration.default_output_subdir
        )

    def _effective_min_label_occurrence(
        self, parameters: LabelAxiomEmergenceWorkflowParameters
    ) -> int:
        value = parameters.min_label_occurrence
        if value is None:
            value = self._configuration.default_min_label_occurrence
        return max(1, value)

    def _effective_min_pair_cooccurrence(
        self, parameters: LabelAxiomEmergenceWorkflowParameters
    ) -> int:
        value = parameters.min_pair_cooccurrence
        if value is None:
            value = self._configuration.default_min_pair_cooccurrence
        return max(1, value)

    def _effective_min_support(
        self, parameters: LabelAxiomEmergenceWorkflowParameters
    ) -> float:
        if parameters.min_support is not None:
            return max(0.0, min(1.0, parameters.min_support))
        return max(0.0, min(1.0, self._configuration.default_min_support))

    def _effective_max_edges(
        self, parameters: LabelAxiomEmergenceWorkflowParameters
    ) -> int:
        value = parameters.max_edges
        if value is None:
            value = self._configuration.default_max_edges
        return max(1, value)

    def _build_labels_query(
        self, parameters: LabelAxiomEmergenceWorkflowParameters
    ) -> str:
        token_filters = self._effective_path_tokens(parameters)
        token_clause = ""
        if token_filters:
            predicates = [
                f'CONTAINS(LCASE(STR(?path)), "{token}")' for token in token_filters
            ]
            token_clause = "FILTER(" + " || ".join(predicates) + ")"

        path_values_clause = ""
        if parameters.paths:
            values = " ".join(rdflib.Literal(path).n3() for path in parameters.paths)
            path_values_clause = f"VALUES ?path {{ {values} }}"

        return f"""PREFIX phases-label: <http://purl.obolibrary.org/obo/phases/labels.owl#>
PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>

SELECT ?label ?label_id ?label_text ?chunk ?chunk_id ?path WHERE {{
  ?label a phases-label:ExtractedLabel ;
         phases-label:label_id ?label_id ;
         phases-label:label_text ?label_text ;
         phases-label:label_from_chunk ?chunk .
  OPTIONAL {{ ?label phases-label:source_chunk_id ?chunk_id . }}
  OPTIONAL {{
    ?chunk phases-doc:chunk_of ?paper .
    ?paper phases-doc:path ?path .
    {path_values_clause}
  }}
  {token_clause}
}}
"""

    def _build_axioms_query(
        self, parameters: LabelAxiomEmergenceWorkflowParameters
    ) -> str:
        token_filters = self._effective_path_tokens(parameters)
        token_clause = ""
        if token_filters:
            predicates = [
                f'CONTAINS(LCASE(STR(?path)), "{token}")' for token in token_filters
            ]
            token_clause = "FILTER(" + " || ".join(predicates) + ")"

        path_values_clause = ""
        if parameters.paths:
            values = " ".join(rdflib.Literal(path).n3() for path in parameters.paths)
            path_values_clause = f"VALUES ?path {{ {values} }}"

        return f"""PREFIX phases-ax: <http://purl.obolibrary.org/obo/phases/axioms.owl#>
PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>

SELECT ?axiom ?axiom_id ?axiom_text ?chunk ?chunk_id ?path WHERE {{
  ?axiom a phases-ax:ExtractedAxiom ;
         phases-ax:axiom_id ?axiom_id ;
         phases-ax:axiom_text ?axiom_text ;
         phases-ax:axiom_from_chunk ?chunk .
  OPTIONAL {{ ?axiom phases-ax:source_chunk_id ?chunk_id . }}
  OPTIONAL {{
    ?chunk phases-doc:chunk_of ?paper .
    ?paper phases-doc:path ?path .
    {path_values_clause}
  }}
  {token_clause}
}}
"""

    def _normalize_label(self, label: str) -> str:
        value = label.strip().lower()
        value = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", value)
        value = value.replace("_", " ").replace("/", " ").replace("-", " ")
        value = re.sub(r"[^a-z0-9\s]", " ", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def _load_labels(
        self, parameters: LabelAxiomEmergenceWorkflowParameters
    ) -> list[LabelObservation]:
        rows = self.module.engine.services.triple_store.query(
            self._build_labels_query(parameters)
        )
        observations: list[LabelObservation] = []
        for row in rows:
            if isinstance(row, bool):
                continue
            try:
                items = tuple(row)
            except TypeError:
                continue
            if len(items) != 6:
                continue

            label_uri, label_id, label_text, chunk_uri, chunk_id, path = items
            label_text_clean = str(label_text or "").strip()
            canonical = self._normalize_label(label_text_clean)
            if not canonical:
                continue

            observations.append(
                LabelObservation(
                    label_uri=str(label_uri or ""),
                    label_id=str(label_id or ""),
                    label_text=label_text_clean,
                    canonical_label=canonical,
                    chunk_uri=str(chunk_uri or ""),
                    chunk_id=str(chunk_id or ""),
                    path=str(path or ""),
                )
            )
        return observations

    def _load_axioms(
        self, parameters: LabelAxiomEmergenceWorkflowParameters
    ) -> list[AxiomObservation]:
        rows = self.module.engine.services.triple_store.query(
            self._build_axioms_query(parameters)
        )
        observations: list[AxiomObservation] = []
        for row in rows:
            if isinstance(row, bool):
                continue
            try:
                items = tuple(row)
            except TypeError:
                continue
            if len(items) != 6:
                continue

            axiom_uri, axiom_id, axiom_text, chunk_uri, chunk_id, path = items
            axiom_text_clean = str(axiom_text or "").strip()
            if not axiom_text_clean:
                continue

            observations.append(
                AxiomObservation(
                    axiom_uri=str(axiom_uri or ""),
                    axiom_id=str(axiom_id or ""),
                    axiom_text=axiom_text_clean,
                    chunk_uri=str(chunk_uri or ""),
                    chunk_id=str(chunk_id or ""),
                    path=str(path or ""),
                )
            )
        return observations

    def _pair_key(self, left: str, right: str) -> tuple[str, str]:
        if left <= right:
            return left, right
        return right, left

    def _labels_in_text(self, text: str, labels: Iterable[str]) -> set[str]:
        lowered = text.lower()
        found: set[str] = set()
        for label in labels:
            pattern = r"(?<![a-z0-9])" + re.escape(label) + r"(?![a-z0-9])"
            if re.search(pattern, lowered):
                found.add(label)
        return found

    def _extract_direction_spans(self, axiom_text: str) -> list[tuple[str, str]]:
        text = re.sub(r"\s+", " ", axiom_text.strip().lower())
        spans: list[tuple[str, str]] = []

        pattern_if_then = re.search(r"\bif\s+(.+?)\s*,?\s*then\s+(.+)", text)
        if pattern_if_then:
            spans.append(
                (pattern_if_then.group(1).strip(), pattern_if_then.group(2).strip())
            )

        directional_patterns = [
            r"(.+?)\s+(?:leads to|results in|predicts|increases|drives|promotes|contributes to)\s+(.+)",
            r"(.+?)\s+(?:is associated with|is linked to)\s+(.+)",
        ]
        for pattern in directional_patterns:
            match = re.search(pattern, text)
            if match:
                spans.append((match.group(1).strip(), match.group(2).strip()))

        reverse_patterns = [
            r"(.+?)\s+(?:is caused by|is predicted by|results from)\s+(.+)",
        ]
        for pattern in reverse_patterns:
            match = re.search(pattern, text)
            if match:
                spans.append((match.group(2).strip(), match.group(1).strip()))

        return spans

    def _clamp(self, value: float) -> float:
        return max(0.0, min(1.0, value))

    def _write_outputs(
        self,
        output_dir: Path,
        edges: list[RelationEdge],
        metadata: dict[str, int | float | str],
    ) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)

        csv_path = output_dir / "label_axiom_emergence_edges.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "source_label",
                    "target_label",
                    "relation_type",
                    "belongs_confidence",
                    "exclusive_to_target_confidence",
                    "co_occurrence_score",
                    "directional_score",
                    "stability_score",
                    "support_score",
                    "co_occurrence_count",
                    "forward_axiom_votes",
                    "reverse_axiom_votes",
                    "evidence_paths_count",
                    "best_alternative_target",
                    "best_alternative_support",
                    "supporting_chunk_ids",
                    "supporting_axiom_ids",
                    "why",
                ]
            )
            for edge in edges:
                writer.writerow(
                    [
                        edge.source_label,
                        edge.target_label,
                        edge.relation_type,
                        f"{edge.belongs_confidence:.6f}",
                        f"{edge.exclusive_to_target_confidence:.6f}",
                        f"{edge.co_occurrence_score:.6f}",
                        f"{edge.directional_score:.6f}",
                        f"{edge.stability_score:.6f}",
                        f"{edge.support_score:.6f}",
                        edge.co_occurrence_count,
                        edge.forward_axiom_votes,
                        edge.reverse_axiom_votes,
                        edge.evidence_paths_count,
                        edge.best_alternative_target,
                        f"{edge.best_alternative_support:.6f}",
                        " | ".join(edge.supporting_chunk_ids),
                        " | ".join(edge.supporting_axiom_ids),
                        edge.why,
                    ]
                )

        json_path = output_dir / "label_axiom_emergence_edges.json"
        payload = {
            "metadata": metadata,
            "edges": [
                {
                    "source_label": edge.source_label,
                    "target_label": edge.target_label,
                    "relation_type": edge.relation_type,
                    "belongs_confidence": edge.belongs_confidence,
                    "exclusive_to_target_confidence": edge.exclusive_to_target_confidence,
                    "co_occurrence_score": edge.co_occurrence_score,
                    "directional_score": edge.directional_score,
                    "stability_score": edge.stability_score,
                    "support_score": edge.support_score,
                    "co_occurrence_count": edge.co_occurrence_count,
                    "forward_axiom_votes": edge.forward_axiom_votes,
                    "reverse_axiom_votes": edge.reverse_axiom_votes,
                    "evidence_paths_count": edge.evidence_paths_count,
                    "best_alternative_target": edge.best_alternative_target,
                    "best_alternative_support": edge.best_alternative_support,
                    "supporting_chunk_ids": edge.supporting_chunk_ids,
                    "supporting_axiom_ids": edge.supporting_axiom_ids,
                    "why": edge.why,
                }
                for edge in edges
            ],
        }
        json_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8"
        )

        graph_path = output_dir / "label_axiom_emergence_graph.json"
        node_set = sorted(
            {edge.source_label for edge in edges}
            | {edge.target_label for edge in edges}
        )
        graph_payload = {
            "nodes": [{"id": node} for node in node_set],
            "edges": [
                {
                    "source": edge.source_label,
                    "target": edge.target_label,
                    "weight": edge.belongs_confidence,
                    "type": edge.relation_type,
                }
                for edge in edges
            ],
        }
        graph_path.write_text(
            json.dumps(graph_payload, ensure_ascii=True, indent=2), encoding="utf-8"
        )

        logger.info(f"Wrote emergence CSV: {csv_path}")
        logger.info(f"Wrote emergence JSON: {json_path}")
        logger.info(f"Wrote emergence graph JSON: {graph_path}")

    def _build_relation_graph(self, edges: list[RelationEdge]) -> rdflib.Graph:
        relations_ns = rdflib.Namespace(
            "http://purl.obolibrary.org/obo/phases/relations.owl#"
        )
        xsd_ns = rdflib.XSD
        rdf_ns = rdflib.RDF

        graph = rdflib.Graph()
        for edge in edges:
            relation_hash = hashlib.sha256(
                f"{edge.source_label}->{edge.target_label}".encode("utf-8")
            ).hexdigest()
            relation_uri = rdflib.URIRef(
                f"http://example.org/instance/phases-relation-{relation_hash}"
            )

            graph.add((relation_uri, rdf_ns.type, relations_ns.InferredLabelRelation))
            graph.add(
                (
                    relation_uri,
                    relations_ns.relation_id,
                    rdflib.Literal(relation_hash, datatype=xsd_ns.string),
                )
            )
            graph.add(
                (
                    relation_uri,
                    relations_ns.source_label_text,
                    rdflib.Literal(edge.source_label, datatype=xsd_ns.string),
                )
            )
            graph.add(
                (
                    relation_uri,
                    relations_ns.target_label_text,
                    rdflib.Literal(edge.target_label, datatype=xsd_ns.string),
                )
            )
            graph.add(
                (
                    relation_uri,
                    relations_ns.relation_type,
                    rdflib.Literal(edge.relation_type, datatype=xsd_ns.string),
                )
            )
            graph.add(
                (
                    relation_uri,
                    relations_ns.belongs_confidence,
                    rdflib.Literal(edge.belongs_confidence, datatype=xsd_ns.float),
                )
            )
            graph.add(
                (
                    relation_uri,
                    relations_ns.exclusive_to_target_confidence,
                    rdflib.Literal(
                        edge.exclusive_to_target_confidence,
                        datatype=xsd_ns.float,
                    ),
                )
            )
            graph.add(
                (
                    relation_uri,
                    relations_ns.co_occurrence_score,
                    rdflib.Literal(edge.co_occurrence_score, datatype=xsd_ns.float),
                )
            )
            graph.add(
                (
                    relation_uri,
                    relations_ns.directional_score,
                    rdflib.Literal(edge.directional_score, datatype=xsd_ns.float),
                )
            )
            graph.add(
                (
                    relation_uri,
                    relations_ns.stability_score,
                    rdflib.Literal(edge.stability_score, datatype=xsd_ns.float),
                )
            )
            graph.add(
                (
                    relation_uri,
                    relations_ns.co_occurrence_count,
                    rdflib.Literal(edge.co_occurrence_count, datatype=xsd_ns.integer),
                )
            )
            graph.add(
                (
                    relation_uri,
                    relations_ns.forward_axiom_votes,
                    rdflib.Literal(edge.forward_axiom_votes, datatype=xsd_ns.integer),
                )
            )
            graph.add(
                (
                    relation_uri,
                    relations_ns.reverse_axiom_votes,
                    rdflib.Literal(edge.reverse_axiom_votes, datatype=xsd_ns.integer),
                )
            )
            graph.add(
                (
                    relation_uri,
                    relations_ns.evidence_paths_count,
                    rdflib.Literal(edge.evidence_paths_count, datatype=xsd_ns.integer),
                )
            )
            graph.add(
                (
                    relation_uri,
                    relations_ns.best_alternative_target,
                    rdflib.Literal(
                        edge.best_alternative_target,
                        datatype=xsd_ns.string,
                    ),
                )
            )
            graph.add(
                (
                    relation_uri,
                    relations_ns.best_alternative_support,
                    rdflib.Literal(
                        edge.best_alternative_support, datatype=xsd_ns.float
                    ),
                )
            )
            graph.add(
                (
                    relation_uri,
                    relations_ns.creation_time,
                    rdflib.Literal(
                        datetime.datetime.now(datetime.UTC), datatype=xsd_ns.dateTime
                    ),
                )
            )

        return graph

    def run(self, parameters: LabelAxiomEmergenceWorkflowParameters):
        logger.info("Running label/axiom emergence workflow from knowledge graph")

        labels = self._load_labels(parameters)
        axioms = self._load_axioms(parameters)

        if len(labels) == 0:
            logger.warning("No labels found for selected filters")
            print("No labels found for selected filters.", flush=True)
            return

        min_label_occurrence = self._effective_min_label_occurrence(parameters)
        min_pair_cooccurrence = self._effective_min_pair_cooccurrence(parameters)
        min_support = self._effective_min_support(parameters)
        max_edges = self._effective_max_edges(parameters)

        label_chunk_ids: dict[str, set[str]] = defaultdict(set)
        label_paths: dict[str, set[str]] = defaultdict(set)
        chunk_to_labels: dict[str, set[str]] = defaultdict(set)
        chunk_to_path: dict[str, str] = {}
        chunk_uri_by_id: dict[str, str] = {}

        for row in labels:
            chunk_key = row.chunk_id or row.chunk_uri
            if not chunk_key:
                continue
            label_chunk_ids[row.canonical_label].add(chunk_key)
            if row.path:
                label_paths[row.canonical_label].add(row.path)
            chunk_to_labels[chunk_key].add(row.canonical_label)
            if row.path:
                chunk_to_path[chunk_key] = row.path
            if row.chunk_uri:
                chunk_uri_by_id[chunk_key] = row.chunk_uri

        eligible_labels = {
            label
            for label, chunks in label_chunk_ids.items()
            if len(chunks) >= min_label_occurrence
        }
        if len(eligible_labels) < 2:
            logger.warning(
                "Not enough labels after min_label_occurrence filtering "
                f"(threshold={min_label_occurrence})"
            )
            print("Not enough labels after filtering.", flush=True)
            return

        pair_chunk_counts: dict[tuple[str, str], int] = defaultdict(int)
        pair_paths: dict[tuple[str, str], set[str]] = defaultdict(set)
        pair_supporting_chunks: dict[tuple[str, str], set[str]] = defaultdict(set)

        for chunk_key, labels_in_chunk in chunk_to_labels.items():
            labels_filtered = sorted(
                label for label in labels_in_chunk if label in eligible_labels
            )
            if len(labels_filtered) < 2:
                continue
            for left_index, left_label in enumerate(labels_filtered):
                for right_label in labels_filtered[left_index + 1 :]:
                    pair_key = self._pair_key(left_label, right_label)
                    pair_chunk_counts[pair_key] += 1
                    pair_supporting_chunks[pair_key].add(chunk_key)
                    path = chunk_to_path.get(chunk_key, "")
                    if path:
                        pair_paths[pair_key].add(path)

        directional_votes: dict[tuple[str, str], int] = defaultdict(int)
        directional_axiom_ids: dict[tuple[str, str], set[str]] = defaultdict(set)

        searchable_labels = sorted(eligible_labels, key=len, reverse=True)
        for axiom in axioms:
            spans = self._extract_direction_spans(axiom.axiom_text)
            if len(spans) == 0:
                continue

            for left_text, right_text in spans:
                left_labels = self._labels_in_text(left_text, searchable_labels)
                right_labels = self._labels_in_text(right_text, searchable_labels)
                if len(left_labels) == 0 or len(right_labels) == 0:
                    continue

                for left_label in left_labels:
                    for right_label in right_labels:
                        if left_label == right_label:
                            continue
                        directional_votes[(left_label, right_label)] += 1
                        if axiom.axiom_id:
                            directional_axiom_ids[(left_label, right_label)].add(
                                axiom.axiom_id
                            )

        candidates: set[tuple[str, str]] = set()
        for pair_key, count in pair_chunk_counts.items():
            if count >= min_pair_cooccurrence:
                left_label, right_label = pair_key
                candidates.add((left_label, right_label))
                candidates.add((right_label, left_label))

        for left_label, right_label in directional_votes.keys():
            if left_label in eligible_labels and right_label in eligible_labels:
                candidates.add((left_label, right_label))

        if len(candidates) == 0:
            logger.warning("No candidate label pairs found")
            print("No candidate relations found.", flush=True)
            return

        support_by_source: dict[str, dict[str, float]] = defaultdict(dict)
        edge_cache: dict[tuple[str, str], dict[str, float | int | str | list[str]]] = {}

        for source_label, target_label in candidates:
            if source_label == target_label:
                continue

            undirected_key = self._pair_key(source_label, target_label)
            co_count = pair_chunk_counts.get(undirected_key, 0)
            source_count = len(label_chunk_ids.get(source_label, set()))
            target_count = len(label_chunk_ids.get(target_label, set()))

            if source_count == 0 or target_count == 0:
                continue

            jaccard = 0.0
            denominator = source_count + target_count - co_count
            if denominator > 0:
                jaccard = co_count / denominator

            ochiai = co_count / math.sqrt(source_count * target_count)
            co_score = self._clamp(0.5 * jaccard + 0.5 * ochiai)

            forward_votes = directional_votes.get((source_label, target_label), 0)
            reverse_votes = directional_votes.get((target_label, source_label), 0)
            directional_score = 0.0
            total_votes = forward_votes + reverse_votes
            if total_votes > 0:
                directional_score = self._clamp(
                    (forward_votes - reverse_votes) / total_votes
                )

            source_paths = label_paths.get(source_label, set())
            target_paths = label_paths.get(target_label, set())
            shared_paths = pair_paths.get(undirected_key, set())
            max_shared = min(len(source_paths), len(target_paths))
            stability_score = 0.0
            if max_shared > 0:
                stability_score = self._clamp(len(shared_paths) / max_shared)

            support_score = self._clamp(
                self._configuration.co_occurrence_weight * co_score
                + self._configuration.directional_weight * directional_score
                + self._configuration.stability_weight * stability_score
            )

            support_by_source[source_label][target_label] = support_score
            edge_cache[(source_label, target_label)] = {
                "co_count": co_count,
                "forward_votes": forward_votes,
                "reverse_votes": reverse_votes,
                "co_score": co_score,
                "directional_score": directional_score,
                "stability_score": stability_score,
                "support_score": support_score,
                "evidence_paths_count": len(shared_paths),
                "supporting_chunk_ids": sorted(
                    pair_supporting_chunks.get(undirected_key, set())
                ),
                "supporting_axiom_ids": sorted(
                    directional_axiom_ids.get((source_label, target_label), set())
                ),
            }

        edges: list[RelationEdge] = []
        for (source_label, target_label), payload in edge_cache.items():
            support_score = float(payload["support_score"])
            if support_score < min_support:
                continue

            alternatives = [
                (candidate, score)
                for candidate, score in support_by_source.get(source_label, {}).items()
                if candidate != target_label
            ]
            alternatives.sort(key=lambda item: item[1], reverse=True)
            if len(alternatives) > 0:
                best_alternative_target, best_alternative_support = alternatives[0]
            else:
                best_alternative_target, best_alternative_support = "", 0.0

            exclusivity = 1.0
            if support_score > 0:
                exclusivity = self._clamp(
                    (support_score - float(best_alternative_support)) / support_score
                )

            directional_score = float(payload["directional_score"])
            co_score = float(payload["co_score"])
            if support_score >= 0.65 and directional_score > 0.2:
                relation_type = "emerges_to"
            elif co_score >= 0.35:
                relation_type = "associated_with"
            else:
                relation_type = "weak_related"

            why = (
                f"co_occurrence_count={int(payload['co_count'])}, "
                f"forward_axiom_votes={int(payload['forward_votes'])}, "
                f"reverse_axiom_votes={int(payload['reverse_votes'])}, "
                f"evidence_paths_count={int(payload['evidence_paths_count'])}"
            )

            edges.append(
                RelationEdge(
                    source_label=source_label,
                    target_label=target_label,
                    relation_type=relation_type,
                    belongs_confidence=support_score,
                    exclusive_to_target_confidence=exclusivity,
                    co_occurrence_score=co_score,
                    directional_score=directional_score,
                    stability_score=float(payload["stability_score"]),
                    co_occurrence_count=int(payload["co_count"]),
                    forward_axiom_votes=int(payload["forward_votes"]),
                    reverse_axiom_votes=int(payload["reverse_votes"]),
                    evidence_paths_count=int(payload["evidence_paths_count"]),
                    best_alternative_target=str(best_alternative_target),
                    best_alternative_support=float(best_alternative_support),
                    support_score=support_score,
                    why=why,
                    supporting_chunk_ids=[
                        str(item) for item in payload["supporting_chunk_ids"]
                    ],
                    supporting_axiom_ids=[
                        str(item) for item in payload["supporting_axiom_ids"]
                    ],
                )
            )

        edges.sort(
            key=lambda edge: (
                -edge.belongs_confidence,
                -edge.exclusive_to_target_confidence,
                edge.source_label,
                edge.target_label,
            )
        )
        edges = edges[:max_edges]

        output_dir = self._effective_output_dir(parameters)
        metadata = {
            "labels_loaded": len(labels),
            "axioms_loaded": len(axioms),
            "eligible_labels": len(eligible_labels),
            "candidate_pairs": len(candidates),
            "edges_kept": len(edges),
            "min_label_occurrence": min_label_occurrence,
            "min_pair_cooccurrence": min_pair_cooccurrence,
            "min_support": min_support,
        }
        self._write_outputs(output_dir=output_dir, edges=edges, metadata=metadata)

        if parameters.persist_relations and not parameters.dry_run and len(edges) > 0:
            graph = self._build_relation_graph(edges)
            if len(graph) > 0:
                self.module.engine.services.triple_store.insert(graph)
                logger.info(f"Persisted inferred relations to KG: {len(edges)}")

        print(f"Output directory: {output_dir}", flush=True)
        print(f"Labels loaded: {len(labels)}", flush=True)
        print(f"Axioms loaded: {len(axioms)}", flush=True)
        print(f"Eligible labels: {len(eligible_labels)}", flush=True)
        print(f"Edges written: {len(edges)}", flush=True)

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Infer directed concept emergence from labels and axioms"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for inferred relation artifacts",
    )
    parser.add_argument(
        "--path",
        dest="paths",
        action="append",
        default=None,
        help="Optional explicit paper path filter (repeatable)",
    )
    parser.add_argument(
        "--path-token",
        dest="path_tokens",
        action="append",
        default=None,
        help="Optional path token filter (repeatable). Default: solitude + paid",
    )
    parser.add_argument(
        "--min-label-occurrence",
        type=int,
        default=None,
        help="Minimum number of chunks required for a canonical label",
    )
    parser.add_argument(
        "--min-pair-cooccurrence",
        type=int,
        default=None,
        help="Minimum chunk-level co-occurrence count for pair seeding",
    )
    parser.add_argument(
        "--min-support",
        type=float,
        default=None,
        help="Minimum support score for keeping an inferred edge",
    )
    parser.add_argument(
        "--max-edges",
        type=int,
        default=None,
        help="Maximum number of edges to keep in outputs",
    )
    parser.add_argument(
        "--persist-relations",
        action="store_true",
        help="Persist inferred relations to the triple store",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and write artifacts without persisting inferred relations",
    )

    args = parser.parse_args()

    workflow = LabelAxiomEmergenceWorkflow(LabelAxiomEmergenceWorkflowConfiguration())
    workflow.run(
        LabelAxiomEmergenceWorkflowParameters(
            output_dir=args.output_dir,
            paths=args.paths,
            path_tokens=args.path_tokens,
            min_label_occurrence=args.min_label_occurrence,
            min_pair_cooccurrence=args.min_pair_cooccurrence,
            min_support=args.min_support,
            max_edges=args.max_edges,
            persist_relations=args.persist_relations,
            dry_run=args.dry_run,
        )
    )
