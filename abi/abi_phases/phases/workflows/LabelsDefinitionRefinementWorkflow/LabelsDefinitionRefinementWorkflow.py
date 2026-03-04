"""Iterative label definition refinement workflow (no graph writes).

Purpose
- Select representative labels from extracted labels using paper-level frequency.
- Gather associated chunks with paper-balanced sampling.
- Build and iteratively refine a definition per label chunk-by-chunk.
- Export draft definitions and revision history for review.

This workflow does not write to the triple store.

How to run (from `abi/`)
- `uv run abi run script abi_phases/phases/workflows/LabelsDefinitionRefinementWorkflow/LabelsDefinitionRefinementWorkflow.py`
- `uv run abi run script abi_phases/phases/workflows/LabelsDefinitionRefinementWorkflow/LabelsDefinitionRefinementWorkflow.py --min-paper-count 2 --label-limit 200 --workers 2`
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, cast

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

from abi_phases.phases import ABIModule


@dataclass
class LabelChunkObservation:
    label_text: str
    chunk_id: str
    chunk_uri: str
    path: str
    chunk_text: str


class LabelsDefinitionRefinementWorkflowConfiguration(WorkflowConfiguration):
    model_name: str = "gpt-5-mini"
    prompt_version: str = "v1"
    model_timeout_seconds: int = 90
    model_max_retries: int = 1
    allowed_path_tokens: list[str] = ["solitude", "paid"]
    default_min_paper_count: int = 2
    default_label_limit: int | None = 200
    default_max_chunks_per_label: int = 12
    default_max_chunks_per_paper: int = 2
    default_workers: int = 1


class LabelsDefinitionRefinementWorkflowParameters(WorkflowParameters):
    output_dir: str
    min_paper_count: int | None = None
    label_limit: int | None = None
    max_chunks_per_label: int | None = None
    max_chunks_per_paper: int | None = None
    workers: int | None = None
    paths: list[str] | None = None
    path_tokens: list[str] | None = None
    dry_run: bool = False


class LabelsDefinitionRefinementWorkflow(
    Workflow[LabelsDefinitionRefinementWorkflowParameters]
):
    module: ABIModule
    _configuration: LabelsDefinitionRefinementWorkflowConfiguration

    def __init__(self, configuration: LabelsDefinitionRefinementWorkflowConfiguration):
        super().__init__(configuration)
        self._configuration = configuration
        self.module = ABIModule.get_instance()
        self._chat_model = ChatOpenAI(
            model=configuration.model_name,
            temperature=0,
            timeout=configuration.model_timeout_seconds,
            max_retries=configuration.model_max_retries,
        )

    def _effective_path_tokens(
        self, parameters: LabelsDefinitionRefinementWorkflowParameters
    ) -> list[str]:
        tokens = parameters.path_tokens or self._configuration.allowed_path_tokens
        return [token.strip().lower() for token in tokens if token.strip()]

    def _build_observations_query(
        self, parameters: LabelsDefinitionRefinementWorkflowParameters
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
            values = " ".join(json.dumps(path) for path in parameters.paths)
            path_values_clause = f"VALUES ?path {{ {values} }}"

        return f"""PREFIX phases-label: <http://purl.obolibrary.org/obo/phases/labels.owl#>
PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>

SELECT ?label_text ?chunk ?chunk_id ?path ?chunk_text
WHERE {{
  ?label a phases-label:ExtractedLabel ;
         phases-label:label_text ?label_text ;
         phases-label:label_from_chunk ?chunk .
  OPTIONAL {{ ?label phases-label:source_chunk_id ?chunk_id . }}
  ?chunk phases-doc:text ?chunk_text ;
         phases-doc:chunk_of ?paper .
  ?paper phases-doc:path ?path .

  {path_values_clause}
  {token_clause}
}}
"""

    def _load_observations(
        self, parameters: LabelsDefinitionRefinementWorkflowParameters
    ) -> list[LabelChunkObservation]:
        rows = self.module.engine.services.triple_store.query(
            self._build_observations_query(parameters)
        )
        observations: list[LabelChunkObservation] = []

        for row in rows:
            if isinstance(row, bool):
                continue
            try:
                items = tuple(row)
            except TypeError:
                continue

            if len(items) != 5:
                continue

            label_text, chunk_uri, chunk_id, path, chunk_text = items
            label = str(label_text or "").strip()
            if not label:
                continue

            observations.append(
                LabelChunkObservation(
                    label_text=label,
                    chunk_id=str(chunk_id or "").strip(),
                    chunk_uri=str(chunk_uri or "").strip(),
                    path=str(path or "").strip(),
                    chunk_text=str(chunk_text or "").strip(),
                )
            )

        return observations

    def _select_chunks_for_label(
        self,
        observations: list[LabelChunkObservation],
        max_chunks_per_label: int,
        max_chunks_per_paper: int,
    ) -> list[LabelChunkObservation]:
        by_path: dict[str, list[LabelChunkObservation]] = defaultdict(list)
        for item in observations:
            if item.path:
                by_path[item.path].append(item)

        for path in by_path:
            by_path[path].sort(key=lambda row: (row.chunk_id, row.chunk_uri))

        selected: list[LabelChunkObservation] = []
        indices: dict[str, int] = {path: 0 for path in by_path.keys()}
        used_per_path: dict[str, int] = {path: 0 for path in by_path.keys()}
        path_order = sorted(by_path.keys())

        while len(selected) < max_chunks_per_label:
            added_any = False
            for path in path_order:
                if len(selected) >= max_chunks_per_label:
                    break
                if used_per_path[path] >= max_chunks_per_paper:
                    continue

                items = by_path[path]
                if indices[path] >= len(items):
                    continue

                selected.append(items[indices[path]])
                indices[path] += 1
                used_per_path[path] += 1
                added_any = True

            if not added_any:
                break

        return selected

    def _initial_state(self, label: str) -> dict[str, Any]:
        return {
            "label": label,
            "definition": "",
            "core_attributes": [],
            "inclusion_criteria": [],
            "exclusion_criteria": [],
            "supporting_chunk_ids": [],
            "conflicting_chunk_ids": [],
            "confidence": 0.0,
            "change_summary": "",
            "verdict": "neutral",
        }

    def _build_refinement_prompt(
        self,
        label: str,
        state: dict[str, Any],
        chunk: LabelChunkObservation,
        step_index: int,
        total_steps: int,
    ) -> str:
        return (
            "You are refining a literature-grounded definition for one label.\n"
            "Use only provided evidence.\n"
            "If the new chunk introduces nuance or conflict, update the definition accordingly.\n\n"
            f"Label: {label}\n"
            f"Step: {step_index}/{total_steps}\n"
            f"Current state JSON:\n{json.dumps(state, ensure_ascii=True)}\n\n"
            "New evidence chunk metadata:\n"
            f"- chunk_id: {chunk.chunk_id}\n"
            f"- path: {chunk.path}\n\n"
            "New evidence chunk text:\n"
            f"{chunk.chunk_text}\n\n"
            "Return STRICT JSON only with this schema:\n"
            "{\n"
            '  "definition": "string",\n'
            '  "core_attributes": ["string"],\n'
            '  "inclusion_criteria": ["string"],\n'
            '  "exclusion_criteria": ["string"],\n'
            '  "supporting_chunk_ids": ["string"],\n'
            '  "conflicting_chunk_ids": ["string"],\n'
            '  "confidence": 0.0,\n'
            '  "change_summary": "string",\n'
            '  "verdict": "supports|extends|contradicts|neutral"\n'
            "}\n"
        )

    def _extract_response_text(self, response: AIMessage) -> str:
        content = response.content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "\n".join(parts)
        return str(content)

    def _parse_payload(self, response_text: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(response_text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", response_text, flags=re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    return None
        return None

    def _clean_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                continue
            text = re.sub(r"\s+", " ", item.strip())
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
        return cleaned

    def _merge_ids(self, old_values: list[str], new_values: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for value in old_values + new_values:
            key = value.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(key)
        return merged

    def _coerce_state(
        self,
        previous: dict[str, Any],
        payload: dict[str, Any] | None,
        current_chunk: LabelChunkObservation,
    ) -> dict[str, Any]:
        if payload is None:
            state = dict(previous)
            state["change_summary"] = "Model returned non-JSON; state unchanged"
            state["verdict"] = "neutral"
            return state

        definition = payload.get("definition")
        if not isinstance(definition, str) or not definition.strip():
            definition = previous.get("definition", "")
        definition = re.sub(r"\s+", " ", definition).strip()

        confidence_raw = payload.get("confidence", previous.get("confidence", 0.0))
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = float(previous.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        verdict_raw = payload.get("verdict", "neutral")
        verdict = str(verdict_raw).strip().lower()
        if verdict not in {"supports", "extends", "contradicts", "neutral"}:
            verdict = "neutral"

        supporting = self._merge_ids(
            self._clean_list(previous.get("supporting_chunk_ids", [])),
            self._clean_list(payload.get("supporting_chunk_ids", [])),
        )
        conflicting = self._merge_ids(
            self._clean_list(previous.get("conflicting_chunk_ids", [])),
            self._clean_list(payload.get("conflicting_chunk_ids", [])),
        )

        if current_chunk.chunk_id:
            if verdict == "contradicts":
                conflicting = self._merge_ids(conflicting, [current_chunk.chunk_id])
            elif verdict in {"supports", "extends"}:
                supporting = self._merge_ids(supporting, [current_chunk.chunk_id])

        change_summary_raw = payload.get("change_summary", "")
        if not isinstance(change_summary_raw, str):
            change_summary_raw = ""
        change_summary = re.sub(r"\s+", " ", change_summary_raw).strip()

        return {
            "label": previous["label"],
            "definition": definition,
            "core_attributes": self._clean_list(payload.get("core_attributes", [])),
            "inclusion_criteria": self._clean_list(
                payload.get("inclusion_criteria", [])
            ),
            "exclusion_criteria": self._clean_list(
                payload.get("exclusion_criteria", [])
            ),
            "supporting_chunk_ids": supporting,
            "conflicting_chunk_ids": conflicting,
            "confidence": confidence,
            "change_summary": change_summary,
            "verdict": verdict,
        }

    def _refine_label_definition(
        self,
        label: str,
        label_observations: list[LabelChunkObservation],
        max_chunks_per_label: int,
        max_chunks_per_paper: int,
    ) -> dict[str, Any]:
        selected_chunks = self._select_chunks_for_label(
            observations=label_observations,
            max_chunks_per_label=max_chunks_per_label,
            max_chunks_per_paper=max_chunks_per_paper,
        )

        state = self._initial_state(label)
        history: list[dict[str, Any]] = []

        for index, chunk in enumerate(selected_chunks, start=1):
            prompt = self._build_refinement_prompt(
                label=label,
                state=state,
                chunk=chunk,
                step_index=index,
                total_steps=len(selected_chunks),
            )

            try:
                response: AIMessage = cast(AIMessage, self._chat_model.invoke(prompt))
                response_text = self._extract_response_text(response)
                payload = self._parse_payload(response_text)
                next_state = self._coerce_state(state, payload, chunk)
            except Exception as exc:
                next_state = dict(state)
                next_state["change_summary"] = f"Model call failed: {exc}"
                next_state["verdict"] = "neutral"

            history.append(
                {
                    "step": index,
                    "chunk_id": chunk.chunk_id,
                    "chunk_uri": chunk.chunk_uri,
                    "path": chunk.path,
                    "verdict": next_state.get("verdict", "neutral"),
                    "confidence": next_state.get("confidence", 0.0),
                    "change_summary": next_state.get("change_summary", ""),
                    "definition": next_state.get("definition", ""),
                }
            )
            state = next_state

        paper_count = len({row.path for row in label_observations if row.path})

        return {
            "label_text": label,
            "paper_count": paper_count,
            "occurrence_count": len(label_observations),
            "chunks_used": len(selected_chunks),
            "chunk_ids_used": [row.chunk_id for row in selected_chunks if row.chunk_id],
            "paths_used": sorted({row.path for row in selected_chunks if row.path}),
            "definition_state": state,
            "history": history,
        }

    def _write_outputs(self, output_dir: Path, results: list[dict[str, Any]]) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)

        full_json = output_dir / "label_definitions_refined.json"
        full_json.write_text(
            json.dumps(results, ensure_ascii=True, indent=2), encoding="utf-8"
        )

        summary_csv = output_dir / "label_definitions_refined_summary.csv"
        with summary_csv.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "label_text",
                    "paper_count",
                    "occurrence_count",
                    "chunks_used",
                    "confidence",
                    "supporting_chunk_ids_count",
                    "conflicting_chunk_ids_count",
                    "definition",
                ]
            )
            for item in results:
                state = item.get("definition_state", {})
                supporting_ids = state.get("supporting_chunk_ids", [])
                conflicting_ids = state.get("conflicting_chunk_ids", [])
                definition = str(state.get("definition", "")).replace("\n", " ")
                writer.writerow(
                    [
                        item.get("label_text", ""),
                        item.get("paper_count", 0),
                        item.get("occurrence_count", 0),
                        item.get("chunks_used", 0),
                        state.get("confidence", 0.0),
                        len(supporting_ids) if isinstance(supporting_ids, list) else 0,
                        len(conflicting_ids)
                        if isinstance(conflicting_ids, list)
                        else 0,
                        definition,
                    ]
                )

        history_jsonl = output_dir / "label_definitions_refined_history.jsonl"
        with history_jsonl.open("w", encoding="utf-8") as file:
            for item in results:
                label = item.get("label_text", "")
                history = item.get("history", [])
                if not isinstance(history, list):
                    continue
                for step in history:
                    if not isinstance(step, dict):
                        continue
                    line = {
                        "label_text": label,
                        **step,
                    }
                    file.write(json.dumps(line, ensure_ascii=True) + "\n")

        logger.info(f"Wrote refined definitions JSON: {full_json}")
        logger.info(f"Wrote refined definitions summary CSV: {summary_csv}")
        logger.info(f"Wrote refinement history JSONL: {history_jsonl}")

    def run(self, parameters: LabelsDefinitionRefinementWorkflowParameters):
        logger.info("Running iterative label definition refinement workflow")
        observations = self._load_observations(parameters)
        if len(observations) == 0:
            logger.warning("No label observations found")
            print(
                "No label observations found for the selected filters.",
                flush=True,
            )
            return

        labels_map: dict[str, list[LabelChunkObservation]] = defaultdict(list)
        for row in observations:
            labels_map[row.label_text].append(row)

        min_paper_count = parameters.min_paper_count
        if min_paper_count is None:
            min_paper_count = self._configuration.default_min_paper_count

        candidates: list[tuple[str, list[LabelChunkObservation], int]] = []
        for label, rows in labels_map.items():
            paper_count = len({item.path for item in rows if item.path})
            if paper_count < min_paper_count:
                continue
            candidates.append((label, rows, paper_count))

        candidates.sort(key=lambda item: (-item[2], -len(item[1]), item[0].lower()))

        label_limit = parameters.label_limit
        if label_limit is None:
            label_limit = self._configuration.default_label_limit
        if label_limit is not None:
            candidates = candidates[: max(0, label_limit)]

        if len(candidates) == 0:
            logger.warning("No labels matched min_paper_count filter")
            print(
                "No labels matched min_paper_count for the selected filters.",
                flush=True,
            )
            return

        max_chunks_per_label = parameters.max_chunks_per_label
        if max_chunks_per_label is None:
            max_chunks_per_label = self._configuration.default_max_chunks_per_label
        max_chunks_per_label = max(1, max_chunks_per_label)

        max_chunks_per_paper = parameters.max_chunks_per_paper
        if max_chunks_per_paper is None:
            max_chunks_per_paper = self._configuration.default_max_chunks_per_paper
        max_chunks_per_paper = max(1, max_chunks_per_paper)

        workers = parameters.workers
        if workers is None:
            workers = self._configuration.default_workers
        workers = max(1, workers)

        if parameters.dry_run:
            first_label, first_rows, _ = candidates[0]
            preview = self._refine_label_definition(
                label=first_label,
                label_observations=first_rows,
                max_chunks_per_label=min(3, max_chunks_per_label),
                max_chunks_per_paper=max_chunks_per_paper,
            )
            output_dir = Path(parameters.output_dir)
            self._write_outputs(output_dir=output_dir, results=[preview])
            state = preview.get("definition_state", {})
            definition_preview = str(state.get("definition", "")).strip()
            if not definition_preview:
                definition_preview = "(empty definition)"
            print(f"[dry-run] Label: {first_label}", flush=True)
            print(f"[dry-run] Paper count: {preview.get('paper_count', 0)}", flush=True)
            print(
                f"[dry-run] Chunks used: {preview.get('chunks_used', 0)}",
                flush=True,
            )
            print(f"[dry-run] Confidence: {state.get('confidence', 0.0)}", flush=True)
            print(f"[dry-run] Definition: {definition_preview}", flush=True)
            print(
                f"[dry-run] Summary CSV: {output_dir / 'label_definitions_refined_summary.csv'}",
                flush=True,
            )
            print(
                f"[dry-run] Full JSON: {output_dir / 'label_definitions_refined.json'}",
                flush=True,
            )
            print(f"[dry-run] Output directory: {output_dir}", flush=True)
            print(f"[dry-run] Processed labels: 1", flush=True)
            return

        results: list[dict[str, Any]] = []
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(
                        self._refine_label_definition,
                        label,
                        rows,
                        max_chunks_per_label,
                        max_chunks_per_paper,
                    )
                    for label, rows, _ in candidates
                ]
                for future in as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        logger.error(f"Label definition refinement failed: {exc}")
        else:
            for label, rows, _ in candidates:
                try:
                    results.append(
                        self._refine_label_definition(
                            label=label,
                            label_observations=rows,
                            max_chunks_per_label=max_chunks_per_label,
                            max_chunks_per_paper=max_chunks_per_paper,
                        )
                    )
                except Exception as exc:
                    logger.error(
                        f"Label definition refinement failed for '{label}': {exc}"
                    )

        results.sort(
            key=lambda item: (
                -int(item.get("paper_count", 0)),
                -int(item.get("occurrence_count", 0)),
                str(item.get("label_text", "")).lower(),
            )
        )

        output_dir = Path(parameters.output_dir)
        self._write_outputs(output_dir=output_dir, results=results)

        print(f"Output directory: {output_dir}", flush=True)
        print(f"Processed labels: {len(results)}", flush=True)

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
        Path(__file__).resolve().parent / "outputs" / "label_definition_refinement"
    )

    parser = argparse.ArgumentParser(
        description="Iteratively refine label definitions from associated chunks"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=default_output,
        help="Output directory for draft definitions",
    )
    parser.add_argument(
        "--min-paper-count",
        type=int,
        default=None,
        help="Keep labels seen in at least this many distinct paper paths",
    )
    parser.add_argument(
        "--label-limit",
        type=int,
        default=None,
        help="Maximum number of labels to process",
    )
    parser.add_argument(
        "--max-chunks-per-label",
        type=int,
        default=None,
        help="Maximum chunks used to refine each label",
    )
    parser.add_argument(
        "--max-chunks-per-paper",
        type=int,
        default=None,
        help="Maximum chunks taken from any single paper path per label",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Parallel workers across labels",
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
        "--dry-run",
        action="store_true",
        help="Process only first label with up to 3 chunks",
    )

    args = parser.parse_args()

    workflow = LabelsDefinitionRefinementWorkflow(
        LabelsDefinitionRefinementWorkflowConfiguration()
    )
    workflow.run(
        LabelsDefinitionRefinementWorkflowParameters(
            output_dir=args.output_dir,
            min_paper_count=args.min_paper_count,
            label_limit=args.label_limit,
            max_chunks_per_label=args.max_chunks_per_label,
            max_chunks_per_paper=args.max_chunks_per_paper,
            workers=args.workers,
            paths=args.paths,
            path_tokens=args.path_tokens,
            dry_run=args.dry_run,
        )
    )
