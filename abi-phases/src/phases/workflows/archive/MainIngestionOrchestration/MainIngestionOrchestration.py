"""Main ingestion orchestration workflow.

Purpose
- Orchestrate all ingestion workflows in the correct order.
- Run independent workflows in parallel.
- Provide idempotent execution (each workflow skips already-processed data).
- Log warnings to both console and file.

Execution Order
1. PapersIngestionWorkflow (sequential)
2. LabelsWorkflow + AxiomsWorkflow (parallel)
3. LabelsEmbeddingWorkflow + AxiomsEmbeddingWorkflow (parallel)
4. LabelsConsolidationWorkflow (sequential)
5. LabelsDefinitionRefinementWorkflow (sequential)
6. LabelAxiomEmergenceWorkflow (sequential)

How to run (from `abi/`)
- `uv run abi run script abi_phases/phases/workflows/MainIngestionOrchestration/MainIngestionOrchestration.py`
- With skips:
  `uv run abi run script abi_phases/phases/workflows/MainIngestionOrchestration/MainIngestionOrchestration.py --skip-extraction`
  `uv run abi run script abi_phases/phases/workflows/MainIngestionOrchestration/MainIngestionOrchestration.py --skip-embedding`
  `uv run abi run script abi_phases/phases/workflows/MainIngestionOrchestration/MainIngestionOrchestration.py --skip-analysis`
- With options:
  `uv run abi run script abi_phases/phases/workflows/MainIngestionOrchestration/MainIngestionOrchestration.py --force --workers 10`
- With custom paths:
  `uv run abi run script abi_phases/phases/workflows/MainIngestionOrchestration/MainIngestionOrchestration.py --papers-path /path/to/papers --ontology-path /path/to/ontology.owl`
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from langchain_core.tools import BaseTool
from naas_abi_core import logger
from naas_abi_core.workflow.workflow import (
    Workflow,
    WorkflowConfiguration,
    WorkflowParameters,
)

from phases.workflows.PapersIngestionWorkflow.PapersIngestionWorkflow import (
    PapersIngestionWorkflow,
    PapersIngestionWorkflowConfiguration,
    PapersIngestionWorkflowParameters,
)
from phases.workflows.archive.LabelsWorkflow.LabelsWorkflow import (
    LabelsWorkflow,
    LabelsWorkflowConfiguration,
    LabelsWorkflowParameters,
)
from phases.workflows.archive.AxiomsWorkflow.AxiomsWorkflow import (
    AxiomsWorkflow,
    AxiomsWorkflowConfiguration,
    AxiomsWorkflowParameters,
)
from phases.workflows.archive.LabelsEmbeddingWorkflow.LabelsEmbeddingWorkflow import (
    LabelsEmbeddingWorkflow,
    LabelsEmbeddingWorkflowConfiguration,
    LabelsEmbeddingWorkflowParameters,
)
from phases.workflows.archive.AxiomsEmbeddingWorkflow.AxiomsEmbeddingWorkflow import (
    AxiomsEmbeddingWorkflow,
    AxiomsEmbeddingWorkflowConfiguration,
    AxiomsEmbeddingWorkflowParameters,
)
from phases.workflows.archive.LabelsConsolidationWorkflow.LabelsConsolidationWorkflow import (
    LabelsConsolidationWorkflow,
    LabelsConsolidationWorkflowConfiguration,
    LabelsConsolidationWorkflowParameters,
)
from phases.workflows.archive.LabelsDefinitionRefinementWorkflow.LabelsDefinitionRefinementWorkflow import (
    LabelsDefinitionRefinementWorkflow,
    LabelsDefinitionRefinementWorkflowConfiguration,
    LabelsDefinitionRefinementWorkflowParameters,
)
from phases.workflows.archive.LabelAxiomEmergenceWorkflow.LabelAxiomEmergenceWorkflow import (
    LabelAxiomEmergenceWorkflow,
    LabelAxiomEmergenceWorkflowConfiguration,
    LabelAxiomEmergenceWorkflowParameters,
)


class MainIngestionOrchestrationConfiguration(WorkflowConfiguration):
    papers_path: str | None = None
    ontology_path: str | None = None
    storage_path: str = "papers"
    default_workers: int = 10


class MainIngestionOrchestrationParameters(WorkflowParameters):
    papers_path: str | None = None
    ontology_path: str | None = None
    papers_paths: list[str] | None = None
    workers: int | None = None
    force: bool = False
    dry_run: bool = False
    skip_extraction: bool = False
    skip_embedding: bool = False
    skip_analysis: bool = False


class WorkflowResult:
    def __init__(self, name: str, success: bool, message: str = ""):
        self.name = name
        self.success = success
        self.message = message


class MainIngestionOrchestration(Workflow[MainIngestionOrchestrationParameters]):
    _configuration: MainIngestionOrchestrationConfiguration
    _run_timestamp: str = ""
    _output_dir: Path | None = None
    _file_handler: logging.FileHandler | None = None

    def __init__(self, configuration: MainIngestionOrchestrationConfiguration):
        super().__init__(configuration)
        self._configuration = configuration

    def _setup_logging(self, output_dir: Path) -> None:
        self._output_dir = output_dir
        log_file = output_dir / "orchestration.log"

        root_logger = logging.getLogger()
        if root_logger.level == logging.NOTSET:
            root_logger.setLevel(logging.DEBUG)

        self._file_handler = logging.FileHandler(log_file, encoding="utf-8")
        self._file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self._file_handler.setFormatter(formatter)
        root_logger.addHandler(self._file_handler)

    def _teardown_logging(self) -> None:
        if self._file_handler:
            self._file_handler.flush()
            self._file_handler.close()
            logging.getLogger().removeHandler(self._file_handler)
            self._file_handler = None

    def _get_output_dir(self) -> Path:
        if self._output_dir is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._run_timestamp = timestamp
            base_dir = Path(__file__).resolve().parent / "outputs"
            self._output_dir = base_dir / f"run_{timestamp}"
        return self._output_dir

    def _log_step_start(self, step_name: str) -> None:
        logger.info(f"{'=' * 60}")
        logger.info(f"STARTING: {step_name}")
        logger.info(f"{'=' * 60}")

    def _log_step_end(self, step_name: str, success: bool, message: str = "") -> None:
        status = "SUCCEEDED" if success else "FAILED"
        logger.info(f"{'=' * 60}")
        logger.info(f"FINISHED: {step_name} [{status}]")
        if message:
            logger.info(f"Message: {message}")
        logger.info(f"{'=' * 60}")

    def _log_warning(self, step_name: str, error: Exception) -> None:
        warning_msg = f"{step_name} failed with error: {error}"
        logger.warning(warning_msg)
        logger.warning(f"Traceback: {traceback.format_exc()}")

    def _run_with_error_handling(
        self, step_name: str, workflow_name: str, run_func, *args, **kwargs
    ) -> WorkflowResult:
        self._log_step_start(step_name)
        try:
            run_func(*args, **kwargs)
            self._log_step_end(step_name, success=True)
            return WorkflowResult(name=workflow_name, success=True)
        except Exception as e:
            self._log_warning(step_name, e)
            self._log_step_end(step_name, success=False, message=str(e))
            return WorkflowResult(name=workflow_name, success=False, message=str(e))

    def _run_papers_ingestion(
        self, parameters: MainIngestionOrchestrationParameters
    ) -> WorkflowResult:
        papers_path = parameters.papers_path
        if papers_path is None:
            papers_path = self._configuration.papers_path
        if papers_path is None:
            papers_path = os.path.join(os.path.dirname(__file__), "..", "..", "papers")

        ontology_path = parameters.ontology_path
        if ontology_path is None:
            ontology_path = self._configuration.ontology_path
        if ontology_path is None:
            ontology_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "ontologies", "phases.owl"
            )

        from glob import glob

        paths = parameters.papers_paths or glob(
            os.path.join(papers_path, "*/*.pdf"), recursive=True
        )

        workflow = PapersIngestionWorkflow(
            PapersIngestionWorkflowConfiguration(
                storage_path=self._configuration.storage_path
            )
        )

        return self._run_with_error_handling(
            "Papers Ingestion",
            "PapersIngestionWorkflow",
            workflow.run,
            PapersIngestionWorkflowParameters(paths=paths, ontology_path=ontology_path),
        )

    def _run_labels_workflow(
        self, parameters: MainIngestionOrchestrationParameters
    ) -> WorkflowResult:
        workflow = LabelsWorkflow(LabelsWorkflowConfiguration())
        return self._run_with_error_handling(
            "Labels Extraction",
            "LabelsWorkflow",
            workflow.run,
            LabelsWorkflowParameters(
                force=parameters.force,
                dry_run=parameters.dry_run,
                workers=parameters.workers,
            ),
        )

    def _run_axioms_workflow(
        self, parameters: MainIngestionOrchestrationParameters
    ) -> WorkflowResult:
        workflow = AxiomsWorkflow(AxiomsWorkflowConfiguration())
        return self._run_with_error_handling(
            "Axioms Extraction",
            "AxiomsWorkflow",
            workflow.run,
            AxiomsWorkflowParameters(
                force=parameters.force,
                dry_run=parameters.dry_run,
                workers=parameters.workers,
            ),
        )

    def _run_labels_embedding_workflow(
        self, parameters: MainIngestionOrchestrationParameters
    ) -> WorkflowResult:
        workflow = LabelsEmbeddingWorkflow(LabelsEmbeddingWorkflowConfiguration())
        return self._run_with_error_handling(
            "Labels Embedding",
            "LabelsEmbeddingWorkflow",
            workflow.run,
            LabelsEmbeddingWorkflowParameters(dry_run=parameters.dry_run),
        )

    def _run_axioms_embedding_workflow(
        self, parameters: MainIngestionOrchestrationParameters
    ) -> WorkflowResult:
        workflow = AxiomsEmbeddingWorkflow(AxiomsEmbeddingWorkflowConfiguration())
        return self._run_with_error_handling(
            "Axioms Embedding",
            "AxiomsEmbeddingWorkflow",
            workflow.run,
            AxiomsEmbeddingWorkflowParameters(dry_run=parameters.dry_run),
        )

    def _run_labels_consolidation_workflow(
        self, parameters: MainIngestionOrchestrationParameters
    ) -> WorkflowResult:
        output_dir = self._get_output_dir()
        consolidation_dir = output_dir / "labels_consolidation"

        workflow = LabelsConsolidationWorkflow(
            LabelsConsolidationWorkflowConfiguration()
        )
        return self._run_with_error_handling(
            "Labels Consolidation",
            "LabelsConsolidationWorkflow",
            workflow.run,
            LabelsConsolidationWorkflowParameters(
                output_dir=str(consolidation_dir),
                dry_run=parameters.dry_run,
            ),
        )

    def _run_labels_definition_refinement_workflow(
        self, parameters: MainIngestionOrchestrationParameters
    ) -> WorkflowResult:
        output_dir = self._get_output_dir()
        refinement_dir = output_dir / "labels_definition_refinement"

        workflow = LabelsDefinitionRefinementWorkflow(
            LabelsDefinitionRefinementWorkflowConfiguration()
        )
        return self._run_with_error_handling(
            "Labels Definition Refinement",
            "LabelsDefinitionRefinementWorkflow",
            workflow.run,
            LabelsDefinitionRefinementWorkflowParameters(
                output_dir=str(refinement_dir),
                dry_run=parameters.dry_run,
            ),
        )

    def _run_label_axiom_emergence_workflow(
        self, parameters: MainIngestionOrchestrationParameters
    ) -> WorkflowResult:
        output_dir = self._get_output_dir()
        emergence_dir = output_dir / "label_axiom_emergence"

        workflow = LabelAxiomEmergenceWorkflow(
            LabelAxiomEmergenceWorkflowConfiguration()
        )
        return self._run_with_error_handling(
            "Label-Axiom Emergence",
            "LabelAxiomEmergenceWorkflow",
            workflow.run,
            LabelAxiomEmergenceWorkflowParameters(
                output_dir=str(emergence_dir),
                dry_run=parameters.dry_run,
                persist_relations=not parameters.dry_run,
            ),
        )

    def _run_parallel(
        self,
        func1,
        func2,
        parameters: MainIngestionOrchestrationParameters,
        name1: str,
        name2: str,
    ) -> tuple[WorkflowResult, WorkflowResult]:
        results: list[WorkflowResult] = [None, None]

        def run_first():
            results[0] = func1(parameters)

        def run_second():
            results[1] = func2(parameters)

        with ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(run_first)
            future2 = executor.submit(run_second)
            future1.result()
            future2.result()

        return results[0], results[1]

    def run(self, parameters: MainIngestionOrchestrationParameters) -> None:
        output_dir = self._get_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        self._setup_logging(output_dir)

        logger.info(f"Starting main ingestion orchestration")
        logger.info(f"Output directory: {output_dir}")
        logger.info(f"Parameters: {parameters.model_dump()}")

        results: list[WorkflowResult] = []

        result = self._run_papers_ingestion(parameters)
        results.append(result)

        if not parameters.skip_extraction and result.success:
            logger.info("Running extraction workflows in parallel...")
            extraction_results = self._run_parallel(
                self._run_labels_workflow,
                self._run_axioms_workflow,
                parameters,
                "LabelsWorkflow",
                "AxiomsWorkflow",
            )
            results.extend(extraction_results)

            if not parameters.skip_embedding:
                logger.info("Running embedding workflows in parallel...")
                embedding_results = self._run_parallel(
                    self._run_labels_embedding_workflow,
                    self._run_axioms_embedding_workflow,
                    parameters,
                    "LabelsEmbeddingWorkflow",
                    "AxiomsEmbeddingWorkflow",
                )
                results.extend(embedding_results)

        if not parameters.skip_analysis:
            result = self._run_labels_consolidation_workflow(parameters)
            results.append(result)

            result = self._run_labels_definition_refinement_workflow(parameters)
            results.append(result)

            result = self._run_label_axiom_emergence_workflow(parameters)
            results.append(result)

        self._teardown_logging()

        logger.info("=" * 60)
        logger.info("ORCHESTRATION COMPLETE")
        logger.info("=" * 60)

        for result in results:
            status = "OK" if result.success else "WARN"
            logger.info(f"  [{status}] {result.name}")
            if result.message:
                logger.info(f"       {result.message}")

        logger.info(f"Log file: {output_dir / 'orchestration.log'}")

        failed = [r for r in results if not r.success]
        if failed:
            logger.warning(
                f"Orchestration completed with {len(failed)} warning(s). "
                "Check log for details. Re-running will resume from last successful step."
            )

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
        description="Main ingestion orchestration - run all ingestion workflows in order"
    )
    parser.add_argument(
        "--papers-path",
        type=str,
        default=None,
        help="Base path containing paper subdirectories",
    )
    parser.add_argument(
        "--ontology-path",
        type=str,
        default=None,
        help="Path to the ontology OWL file",
    )
    parser.add_argument(
        "--papers-path-override",
        dest="papers_paths",
        action="append",
        default=None,
        help="Specific paper paths to process (can be repeated)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers for extraction workflows",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reprocessing of already processed data",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Audit mode - process only first chunk, do not persist",
    )
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Skip LabelsWorkflow and AxiomsWorkflow",
    )
    parser.add_argument(
        "--skip-embedding",
        action="store_true",
        help="Skip LabelsEmbeddingWorkflow and AxiomsEmbeddingWorkflow",
    )
    parser.add_argument(
        "--skip-analysis",
        action="store_true",
        help="Skip consolidation, refinement, and emergence workflows",
    )

    args = parser.parse_args()

    workflow = MainIngestionOrchestration(MainIngestionOrchestrationConfiguration())
    workflow.run(
        MainIngestionOrchestrationParameters(
            papers_path=args.papers_path,
            ontology_path=args.ontology_path,
            papers_paths=args.papers_paths,
            workers=args.workers,
            force=args.force,
            dry_run=args.dry_run,
            skip_extraction=args.skip_extraction,
            skip_embedding=args.skip_embedding,
            skip_analysis=args.skip_analysis,
        )
    )
