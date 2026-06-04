import dagster as dg
from naas_abi_core.orchestrations.DagsterOrchestration import DagsterOrchestration


import os
from glob import glob
from pathlib import Path

from phases.workflows.PapersIngestionWorkflow.PapersIngestionWorkflow import (
    PapersIngestionWorkflow,
    PapersIngestionWorkflowConfiguration,
    PapersIngestionWorkflowParameters,
)
from phases.workflows.GenericChunkExtractionWorkflow.run_extraction import (
    PIPELINES,
    _run_one,
)
from phases.workflows.PapersIngestionWorkflow.normalize_paths_migration import (
    normalize_paper_paths,
)
from phases.workflows.ExtractedItemsEmbeddingWorkflow.ExtractedItemsEmbeddingWorkflow import (
    ExtractedItemsEmbeddingWorkflow,
    ExtractedItemsEmbeddingWorkflowConfiguration,
    ExtractedItemsEmbeddingWorkflowParameters,
)
from phases.workflows.ProcessDispositionExtractionWorkflow.ProcessDispositionExtractionWorkflow import (
    ProcessDispositionExtractionWorkflow,
    ProcessDispositionExtractionWorkflowConfiguration,
    ProcessDispositionExtractionWorkflowParameters,
)

PROCESS_DISPOSITION_PROMPT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "workflows",
        "ProcessDispositionExtractionWorkflow",
        "prompts",
        "probabilistic_processes.txt",
    )
)

EXTRACTIONS_OUTPUT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "storage", "extractions")
)


def ingest_papers(path: str) -> None:
    ONTOLOGY_PATH = os.path.join(
        os.path.dirname(__file__), "..", "ontologies", "phases.owl"
    )
    
    workflow = PapersIngestionWorkflow(PapersIngestionWorkflowConfiguration())
    workflow.run(
        PapersIngestionWorkflowParameters(
            paths=sorted(glob(path)),
            ontology_path=os.path.abspath(ONTOLOGY_PATH),
        )
    )
    
@dg.op
def ingest_solitude_papers_op(context: dg.OpExecutionContext) -> None:
    """Run PapersIngestionWorkflow scoped to abi/src/phases/papers/solitude/pmc."""
    
    
    


    context.log.info("1/3 Starting solitude papers ingestion")
    ingest_papers(os.path.join(os.path.join(os.path.dirname(__file__), "..", "papers", "solitude"), "*.pdf"))
    
    context.log.info("2/3 Starting solitude pmc papers ingestion")
    ingest_papers(os.path.join(os.path.join(os.path.dirname(__file__), "..", "papers", "solitude", "pmc"), "*.pdf"))
    
    context.log.info("SKIPPING FOR NOW 3/3 Starting solitude paid papers ingestion")

    context.log.info("Finished all solitude papers ingestion")


@dg.op
def ingest_gero_papers_op(context: dg.OpExecutionContext) -> None:
    """Run PapersIngestionWorkflow scoped to abi/src/phases/papers/gero (and gero/pmc)."""

    context.log.info("1/2 Starting gerotranscendence papers ingestion")
    ingest_papers(os.path.join(os.path.join(os.path.dirname(__file__), "..", "papers", "gero"), "*.pdf"))

    context.log.info("2/2 Starting gerotranscendence pmc papers ingestion")
    ingest_papers(os.path.join(os.path.join(os.path.dirname(__file__), "..", "papers", "gero", "pmc"), "*.pdf"))

    context.log.info("Finished all gerotranscendence papers ingestion")


PAPERS_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "papers")
)


class ExtractionConfig(dg.Config):
    paper_path_glob: str | None = "solitude/*.pdf"
    """Non-recursive glob, relative to abi/src/phases/papers.

    Examples:
      - "solitude/*.pdf"     -> only papers directly under solitude/ (no /pmc) — DEFAULT
      - "solitude/pmc/*.pdf" -> only papers under solitude/pmc/
      - None                 -> all chunks in the triple store
    """
    model: str = "gpt-5-mini"
    chunk_limit: int | None = None
    workers: int | None = None


@dg.op(ins={"start": dg.In(dg.Nothing)})
def run_solitude_extractions_op(
    context: dg.OpExecutionContext, config: ExtractionConfig
) -> None:
    """Run every named pipeline from run_extraction.py over solitude chunks."""
    out = Path(EXTRACTIONS_OUTPUT_DIR)
    out.mkdir(parents=True, exist_ok=True)

    paths: list[str] | None = None
    if config.paper_path_glob:
        pattern = os.path.join(PAPERS_ROOT, config.paper_path_glob)
        paths = sorted(glob(pattern))
        context.log.info(
            f"Scoping extraction to {len(paths)} paper(s) matching {pattern}"
        )
        if not paths:
            context.log.warning(
                f"paper_path_glob '{config.paper_path_glob}' matched no files — "
                "extraction will be skipped."
            )
            return
    else:
        context.log.info("No paper_path_glob set — running over ALL chunks.")

    for name in PIPELINES:
        target = str(out / f"{name}.json")
        context.log.info(f"Running extraction pipeline: {name}")
        results = _run_one(
            name,
            paths=paths,
            chunk_limit=config.chunk_limit,
            workers=config.workers,
            model=config.model,
            output_path=target,
            dry_run=False,
        )
        context.log.info(
            f"[{name}] processed {len(results)} chunks -> {target}"
        )


class GeroExtractionConfig(dg.Config):
    paper_path_glob: str | None = "gero/pmc/*.pdf"
    """Non-recursive glob, relative to abi/src/phases/papers.

    Examples:
      - "gero/pmc/*.pdf" -> only papers under gero/pmc/ — DEFAULT
      - "gero/*.pdf"     -> only papers directly under gero/
      - None             -> all chunks in the triple store
    """
    model: str = "gpt-5-mini"
    chunk_limit: int | None = None
    workers: int | None = None


@dg.op(ins={"start": dg.In(dg.Nothing)})
def run_gero_extractions_op(
    context: dg.OpExecutionContext, config: GeroExtractionConfig
) -> None:
    """Run every named pipeline from run_extraction.py over gerotranscendence chunks."""
    out = Path(EXTRACTIONS_OUTPUT_DIR)
    out.mkdir(parents=True, exist_ok=True)

    paths: list[str] | None = None
    if config.paper_path_glob:
        pattern = os.path.join(PAPERS_ROOT, config.paper_path_glob)
        paths = sorted(glob(pattern))
        context.log.info(
            f"Scoping extraction to {len(paths)} paper(s) matching {pattern}"
        )
        if not paths:
            context.log.warning(
                f"paper_path_glob '{config.paper_path_glob}' matched no files — "
                "extraction will be skipped."
            )
            return
    else:
        context.log.info("No paper_path_glob set — running over ALL chunks.")

    for name in PIPELINES:
        target = str(out / f"{name}.json")
        context.log.info(f"Running extraction pipeline: {name}")
        results = _run_one(
            name,
            paths=paths,
            chunk_limit=config.chunk_limit,
            workers=config.workers,
            model=config.model,
            output_path=target,
            dry_run=False,
        )
        context.log.info(
            f"[{name}] processed {len(results)} chunks -> {target}"
        )


class ProcessDispositionExtractionConfig(dg.Config):
    paper_path_glob: str | None = None
    """Non-recursive glob, relative to abi/src/phases/papers.

    Examples:
      - "solitude/*.pdf"     -> only papers directly under solitude/
      - "gero/pmc/*.pdf"     -> only papers under gero/pmc/
      - None                 -> all chunks in the triple store — DEFAULT
    """
    model: str = "gpt-5-mini"
    chunk_limit: int | None = None
    workers: int | None = None
    max_relations_per_chunk: int = 8
    link_to_labels: bool = True


def _run_process_disposition_extraction(
    context: dg.OpExecutionContext,
    config: ProcessDispositionExtractionConfig,
) -> None:
    """Shared body used by the standalone job and the chained jobs."""
    paths: list[str] | None = None
    if config.paper_path_glob:
        pattern = os.path.join(PAPERS_ROOT, config.paper_path_glob)
        paths = sorted(glob(pattern))
        context.log.info(
            f"Scoping process-disposition extraction to {len(paths)} paper(s) "
            f"matching {pattern}"
        )
        if not paths:
            context.log.warning(
                f"paper_path_glob '{config.paper_path_glob}' matched no files — "
                "process-disposition extraction will be skipped."
            )
            return
    else:
        context.log.info(
            "No paper_path_glob set — running over ALL chunks for "
            "process-disposition extraction."
        )

    prompt_template = Path(PROCESS_DISPOSITION_PROMPT_PATH).read_text()
    workflow = ProcessDispositionExtractionWorkflow(
        ProcessDispositionExtractionWorkflowConfiguration(
            prompt_template=prompt_template,
            model_name=config.model,
            max_relations_per_chunk=config.max_relations_per_chunk,
            link_to_labels=config.link_to_labels,
        )
    )
    out = Path(EXTRACTIONS_OUTPUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    output_path = str(out / "process_dispositions.json")

    results = workflow.run(
        ProcessDispositionExtractionWorkflowParameters(
            paths=paths,
            chunk_limit=config.chunk_limit,
            workers=config.workers,
            output_path=output_path,
            dry_run=False,
        )
    )
    total_relations = sum(len(v) for v in results.values())
    context.log.info(
        f"[process_dispositions] processed {len(results)} chunks, "
        f"{total_relations} relations -> {output_path}"
    )


@dg.op(ins={"start": dg.In(dg.Nothing)})
def run_process_disposition_extraction_chained_op(
    context: dg.OpExecutionContext, config: ProcessDispositionExtractionConfig
) -> None:
    """Chained variant: takes a Nothing input so it can be wired after another op."""
    _run_process_disposition_extraction(context, config)


@dg.op
def run_process_disposition_extraction_op(
    context: dg.OpExecutionContext, config: ProcessDispositionExtractionConfig
) -> None:
    """Standalone variant: runnable on its own from the Dagster UI."""
    _run_process_disposition_extraction(context, config)


@dg.op(ins={"start": dg.In(dg.Nothing)})
def embed_extracted_items_op(context: dg.OpExecutionContext) -> None:
    """Embed every ExtractedItem.extracted_text into the vector store."""
    workflow = ExtractedItemsEmbeddingWorkflow(
        ExtractedItemsEmbeddingWorkflowConfiguration()
    )
    embedded = workflow.run(ExtractedItemsEmbeddingWorkflowParameters())
    context.log.info(f"Embedded {embedded} new ExtractedItem(s)")


@dg.op
def normalize_paper_paths_op(context: dg.OpExecutionContext) -> None:
    """One-shot migration to rewrite stored PDFPaperFile paths to absolute form."""
    rewrites = normalize_paper_paths()
    context.log.info(f"normalize_paper_paths rewrote {rewrites} triple(s)")


@dg.job(
    name="normalize_paper_paths",
    description=(
        "Rewrite phases-doc:path literals on existing PDFPaperFile records "
        "to their os.path.abspath form. Idempotent."
    ),
)
def normalize_paper_paths_job() -> None:
    normalize_paper_paths_op()


@dg.job(
    name="ingest_solitude_papers",
    description=(
        "Ingest the solitude papers, run every GenericChunkExtractionWorkflow "
        "pipeline (causes / how / when / where / effects), embed the resulting "
        "ExtractedItem texts, and extract probability-modulating BFO "
        "process-disposition relations."
    ),
)
def ingest_solitude_papers_job() -> None:
    after_embed = embed_extracted_items_op(
        start=run_solitude_extractions_op(start=ingest_solitude_papers_op())
    )
    run_process_disposition_extraction_chained_op(start=after_embed)


@dg.job(
    name="ingest_gero_papers",
    description=(
        "Ingest the gerotranscendence papers, run every GenericChunkExtractionWorkflow "
        "pipeline (causes / how / when / where / effects), embed the resulting "
        "ExtractedItem texts, and extract probability-modulating BFO "
        "process-disposition relations."
    ),
)
def ingest_gero_papers_job() -> None:
    after_embed = embed_extracted_items_op(
        start=run_gero_extractions_op(start=ingest_gero_papers_op())
    )
    run_process_disposition_extraction_chained_op(start=after_embed)


@dg.job(
    name="run_process_disposition_extraction",
    description=(
        "Extract probability-modulating BFO process-disposition relations from "
        "every candidate chunk (or only those matching paper_path_glob). "
        "Idempotent on (prompt_hash, model_name); already-processed chunks are "
        "skipped."
    ),
)
def run_process_disposition_extraction_job() -> None:
    run_process_disposition_extraction_op()


class PhasesOrchestration(DagsterOrchestration):

    @classmethod
    def New(cls) -> "PhasesOrchestration":
        return cls(
            definitions=dg.Definitions(
                assets=[],
                schedules=[],
                jobs=[
                    ingest_solitude_papers_job,
                    ingest_gero_papers_job,
                    run_process_disposition_extraction_job,
                    normalize_paper_paths_job,
                ],
                sensors=[],
            )
        )
