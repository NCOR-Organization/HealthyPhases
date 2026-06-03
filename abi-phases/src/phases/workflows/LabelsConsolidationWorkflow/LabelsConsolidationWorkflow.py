"""Labels consolidation workflow (no graph writes).

Purpose
- Read extracted labels and their source chunks from the triple store.
- Consolidate labels with deterministic normalization.
- Optionally merge semantically similar labels using embeddings.
- Export merge artifacts for manual review and downstream definition generation.

This workflow does not update the triple store.

How to run (from `abi/`)
- `uv run abi run script abi_phases/phases/workflows/LabelsConsolidationWorkflow/LabelsConsolidationWorkflow.py`
- `uv run abi run script abi_phases/phases/workflows/LabelsConsolidationWorkflow/LabelsConsolidationWorkflow.py --auto-merge-threshold 0.92 --review-threshold 0.85`
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np
from fastapi import APIRouter
from langchain_core.tools import BaseTool
from langchain_openai import OpenAIEmbeddings
from naas_abi_core import logger
from naas_abi_core.workflow.workflow import (
    Workflow,
    WorkflowConfiguration,
    WorkflowParameters,
)

from phases import ABIModule


@dataclass
class LabelObservation:
    label_text: str
    chunk_id: str
    chunk_uri: str
    path: str
    chunk_text: str


@dataclass
class CanonicalLabelStats:
    canonical_label: str
    total_count: int
    variants: list[str]
    chunk_ids: list[str]
    sample_paths: list[str]
    sample_chunk_texts: list[str]


class LabelsConsolidationWorkflowConfiguration(WorkflowConfiguration):
    embedding_model_name: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072
    embedding_batch_size: int = 64
    auto_merge_threshold: float = 0.92
    review_threshold: float = 0.85
    max_paths_per_label: int = 5
    max_chunk_ids_per_label: int = 25
    max_chunk_text_examples: int = 3
    allowed_path_tokens: list[str] = ["solitude", "paid"]


class LabelsConsolidationWorkflowParameters(WorkflowParameters):
    output_dir: str
    paths: list[str] | None = None
    path_tokens: list[str] | None = None
    auto_merge_threshold: float | None = None
    review_threshold: float | None = None
    disable_semantic_merge: bool = False


class LabelsConsolidationWorkflow(Workflow[LabelsConsolidationWorkflowParameters]):
    module: ABIModule
    _configuration: LabelsConsolidationWorkflowConfiguration

    def __init__(self, configuration: LabelsConsolidationWorkflowConfiguration):
        super().__init__(configuration)
        self._configuration = configuration
        self.module = ABIModule.get_instance()
        self._embeddings = OpenAIEmbeddings(
            model=configuration.embedding_model_name,
            dimensions=configuration.embedding_dimensions,
        )

    def _effective_tokens(
        self, parameters: LabelsConsolidationWorkflowParameters
    ) -> list[str]:
        tokens = (
            parameters.path_tokens
            if parameters.path_tokens is not None
            else self._configuration.allowed_path_tokens
        )
        cleaned = [token.strip().lower() for token in tokens if token.strip()]
        return cleaned

    def _build_query(self, parameters: LabelsConsolidationWorkflowParameters) -> str:
        values_clause = ""
        if parameters.paths:
            values = " ".join(f'"{path}"' for path in parameters.paths)
            values_clause = f"VALUES ?path {{ {values} }}"

        token_filters = self._effective_tokens(parameters)
        token_clause = ""
        if token_filters:
            predicates = [
                f'CONTAINS(LCASE(STR(?path)), "{token}")' for token in token_filters
            ]
            token_clause = "FILTER(" + " || ".join(predicates) + ")"

        return f"""PREFIX phases-label: <http://purl.obolibrary.org/obo/phases/labels.owl#>
PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>

SELECT ?label_text ?chunk ?chunk_id ?path ?chunk_text
WHERE {{
  ?label a phases-label:ExtractedLabel ;
         phases-label:label_text ?label_text ;
         phases-label:label_from_chunk ?chunk .

  OPTIONAL {{ ?label phases-label:source_chunk_id ?chunk_id . }}
  OPTIONAL {{ ?chunk phases-doc:text ?chunk_text . }}
  OPTIONAL {{
    ?chunk phases-doc:chunk_of ?pdf_paper_file .
    ?pdf_paper_file phases-doc:path ?path .
    {values_clause}
  }}

  {token_clause}
}}
"""

    def _load_observations(
        self, parameters: LabelsConsolidationWorkflowParameters
    ) -> list[LabelObservation]:
        rows = self.module.engine.services.triple_store.query(
            self._build_query(parameters)
        )
        observations: list[LabelObservation] = []
        for row in rows:
            if isinstance(row, bool):
                continue
            items = tuple(row)
            if len(items) != 5:
                continue
            label_text, chunk_uri, chunk_id, path, chunk_text = items
            observations.append(
                LabelObservation(
                    label_text=str(label_text or "").strip(),
                    chunk_id=str(chunk_id or ""),
                    chunk_uri=str(chunk_uri or ""),
                    path=str(path or ""),
                    chunk_text=str(chunk_text or ""),
                )
            )
        return observations

    def _normalize_label(self, label: str) -> str:
        value = label.strip().lower()
        value = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", value)
        value = value.replace("_", " ").replace("/", " ").replace("-", " ")
        value = re.sub(r"[^a-z0-9\s]", " ", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def _group_by_normalized(
        self, observations: list[LabelObservation]
    ) -> tuple[dict[str, list[LabelObservation]], dict[str, int]]:
        groups: dict[str, list[LabelObservation]] = defaultdict(list)
        raw_counts: dict[str, int] = defaultdict(int)

        for item in observations:
            if not item.label_text:
                continue
            raw_counts[item.label_text] += 1
            normalized = self._normalize_label(item.label_text)
            if not normalized:
                continue
            groups[normalized].append(item)

        return groups, raw_counts

    def _embed_texts(self, texts: list[str]) -> np.ndarray:
        vectors: list[np.ndarray] = []
        batch_size = max(1, self._configuration.embedding_batch_size)
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            embeddings = self._embeddings.embed_documents(batch)
            vectors.extend(np.array(vector) for vector in embeddings)
        matrix = np.vstack(vectors)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms

    def _build_semantic_parent(
        self,
        canonicals: list[str],
        auto_merge_threshold: float,
        review_threshold: float,
    ) -> tuple[dict[int, int], list[tuple[str, str, float]]]:
        parent: dict[int, int] = {index: index for index in range(len(canonicals))}

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            root_left = find(left)
            root_right = find(right)
            if root_left != root_right:
                parent[root_right] = root_left

        review_pairs: list[tuple[str, str, float]] = []

        if len(canonicals) < 2:
            return parent, review_pairs

        vectors = self._embed_texts(canonicals)
        for i in range(len(canonicals)):
            similarities = vectors[i + 1 :] @ vectors[i]
            for offset, score in enumerate(similarities, start=1):
                j = i + offset
                similarity = float(score)
                if similarity >= auto_merge_threshold:
                    union(i, j)
                elif similarity >= review_threshold:
                    review_pairs.append((canonicals[i], canonicals[j], similarity))

        return parent, review_pairs

    def _select_cluster_representative(
        self,
        cluster: list[str],
        groups: dict[str, list[LabelObservation]],
    ) -> str:
        def rank_key(label: str) -> tuple[int, int, str]:
            return (-len(groups[label]), len(label), label)

        ranked = sorted(cluster, key=rank_key)
        return ranked[0]

    def _cluster_map(
        self,
        canonicals: list[str],
        parent: dict[int, int],
        groups: dict[str, list[LabelObservation]],
    ) -> tuple[dict[str, str], dict[str, list[str]]]:
        clusters: dict[int, list[str]] = defaultdict(list)

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        for index, label in enumerate(canonicals):
            clusters[find(index)].append(label)

        canonical_map: dict[str, str] = {}
        cluster_variants: dict[str, list[str]] = {}

        for cluster_labels in clusters.values():
            representative = self._select_cluster_representative(cluster_labels, groups)
            cluster_variants[representative] = sorted(cluster_labels)
            for label in cluster_labels:
                canonical_map[label] = representative

        return canonical_map, cluster_variants

    def _build_stats(
        self,
        groups: dict[str, list[LabelObservation]],
        canonical_map: dict[str, str],
        cluster_variants: dict[str, list[str]],
    ) -> list[CanonicalLabelStats]:
        aggregated: dict[str, list[LabelObservation]] = defaultdict(list)
        for normalized_label, observations in groups.items():
            canonical = canonical_map[normalized_label]
            aggregated[canonical].extend(observations)

        stats: list[CanonicalLabelStats] = []
        for canonical, observations in aggregated.items():
            seen_chunk_ids: set[str] = set()
            chunk_ids: list[str] = []
            seen_paths: set[str] = set()
            sample_paths: list[str] = []
            sample_chunk_texts: list[str] = []

            for item in observations:
                if item.chunk_id and item.chunk_id not in seen_chunk_ids:
                    seen_chunk_ids.add(item.chunk_id)
                    if len(chunk_ids) < self._configuration.max_chunk_ids_per_label:
                        chunk_ids.append(item.chunk_id)
                if item.path and item.path not in seen_paths:
                    seen_paths.add(item.path)
                    if len(sample_paths) < self._configuration.max_paths_per_label:
                        sample_paths.append(item.path)
                if (
                    item.chunk_text
                    and len(sample_chunk_texts)
                    < self._configuration.max_chunk_text_examples
                ):
                    sample_chunk_texts.append(item.chunk_text)

            stats.append(
                CanonicalLabelStats(
                    canonical_label=canonical,
                    total_count=len(observations),
                    variants=cluster_variants.get(canonical, [canonical]),
                    chunk_ids=chunk_ids,
                    sample_paths=sample_paths,
                    sample_chunk_texts=sample_chunk_texts,
                )
            )

        stats.sort(key=lambda item: (-item.total_count, item.canonical_label))
        return stats

    def _write_outputs(
        self,
        output_dir: Path,
        stats: list[CanonicalLabelStats],
        groups: dict[str, list[LabelObservation]],
        canonical_map: dict[str, str],
        review_pairs: list[tuple[str, str, float]],
    ) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)

        canonical_csv = output_dir / "canonical_labels.csv"
        with canonical_csv.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "canonical_label",
                    "total_count",
                    "variants_count",
                    "variants",
                    "chunk_ids",
                    "sample_paths",
                ]
            )
            for row in stats:
                writer.writerow(
                    [
                        row.canonical_label,
                        row.total_count,
                        len(row.variants),
                        " | ".join(row.variants),
                        " | ".join(row.chunk_ids),
                        " | ".join(row.sample_paths),
                    ]
                )

        merge_map_csv = output_dir / "label_merge_map.csv"
        with merge_map_csv.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "normalized_label",
                    "canonical_label",
                    "observations_count",
                    "distinct_chunk_count",
                ]
            )
            for normalized_label in sorted(groups.keys()):
                observations = groups[normalized_label]
                distinct_chunks = len(
                    {item.chunk_id for item in observations if item.chunk_id.strip()}
                )
                writer.writerow(
                    [
                        normalized_label,
                        canonical_map[normalized_label],
                        len(observations),
                        distinct_chunks,
                    ]
                )

        review_csv = output_dir / "semantic_review_pairs.csv"
        with review_csv.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["label_a", "label_b", "cosine_similarity"])
            for label_a, label_b, similarity in sorted(
                review_pairs, key=lambda item: -item[2]
            ):
                writer.writerow([label_a, label_b, f"{similarity:.6f}"])

        definitions_json = output_dir / "canonical_labels_for_definitions.json"
        payload = [
            {
                "canonical_label": item.canonical_label,
                "total_count": item.total_count,
                "variants": item.variants,
                "chunk_ids": item.chunk_ids,
                "sample_paths": item.sample_paths,
                "sample_chunk_texts": item.sample_chunk_texts,
            }
            for item in stats
        ]
        definitions_json.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8"
        )

        logger.info(f"Wrote canonical labels CSV: {canonical_csv}")
        logger.info(f"Wrote merge map CSV: {merge_map_csv}")
        logger.info(f"Wrote semantic review CSV: {review_csv}")
        logger.info(f"Wrote definitions seed JSON: {definitions_json}")

    def run(self, parameters: LabelsConsolidationWorkflowParameters):
        logger.info("Running labels consolidation workflow (no graph writes)")
        observations = self._load_observations(parameters)
        if len(observations) == 0:
            logger.warning("No label observations found for consolidation")
            return

        groups, _ = self._group_by_normalized(observations)
        if len(groups) == 0:
            logger.warning("No normalized labels available after cleaning")
            return

        auto_merge_threshold = (
            parameters.auto_merge_threshold
            if parameters.auto_merge_threshold is not None
            else self._configuration.auto_merge_threshold
        )
        review_threshold = (
            parameters.review_threshold
            if parameters.review_threshold is not None
            else self._configuration.review_threshold
        )

        canonicals = sorted(groups.keys())
        if parameters.disable_semantic_merge:
            parent = {index: index for index in range(len(canonicals))}
            review_pairs: list[tuple[str, str, float]] = []
        else:
            parent, review_pairs = self._build_semantic_parent(
                canonicals=canonicals,
                auto_merge_threshold=auto_merge_threshold,
                review_threshold=review_threshold,
            )

        canonical_map, cluster_variants = self._cluster_map(
            canonicals=canonicals,
            parent=parent,
            groups=groups,
        )

        stats = self._build_stats(
            groups=groups,
            canonical_map=canonical_map,
            cluster_variants=cluster_variants,
        )

        output_dir = Path(parameters.output_dir)
        self._write_outputs(
            output_dir=output_dir,
            stats=stats,
            groups=groups,
            canonical_map=canonical_map,
            review_pairs=review_pairs,
        )

        logger.info(
            "Consolidation done: "
            f"observations={len(observations)} "
            f"normalized={len(groups)} "
            f"canonical={len(stats)} "
            f"review_pairs={len(review_pairs)}"
        )
        print(f"Output directory: {output_dir}", flush=True)
        print(f"Observations: {len(observations)}", flush=True)
        print(f"Normalized labels: {len(groups)}", flush=True)
        print(f"Canonical labels: {len(stats)}", flush=True)
        print(f"Review pairs: {len(review_pairs)}", flush=True)

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
    default_output = str(
        Path(__file__).resolve().parent / "outputs" / "labels_consolidation"
    )

    parser = argparse.ArgumentParser(
        description="Consolidate labels into canonical forms without graph updates"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=default_output,
        help="Directory where CSV/JSON artifacts will be written",
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
        "--auto-merge-threshold",
        type=float,
        default=None,
        help="Cosine threshold for automatic semantic merges (default: 0.92)",
    )
    parser.add_argument(
        "--review-threshold",
        type=float,
        default=None,
        help="Cosine threshold for review candidate pairs (default: 0.85)",
    )
    parser.add_argument(
        "--disable-semantic-merge",
        action="store_true",
        help="Only apply deterministic normalization; skip embedding-based merges",
    )

    args = parser.parse_args()

    workflow = LabelsConsolidationWorkflow(LabelsConsolidationWorkflowConfiguration())
    workflow.run(
        LabelsConsolidationWorkflowParameters(
            output_dir=args.output_dir,
            paths=args.paths,
            path_tokens=args.path_tokens,
            auto_merge_threshold=args.auto_merge_threshold,
            review_threshold=args.review_threshold,
            disable_semantic_merge=args.disable_semantic_merge,
        )
    )
