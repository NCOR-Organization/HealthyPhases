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
        "pipeline (causes / how / when / where / effects), and embed the resulting "
        "ExtractedItem texts so they can be searched."
    ),
)
def ingest_solitude_papers_job() -> None:
    embed_extracted_items_op(
        start=run_solitude_extractions_op(start=ingest_solitude_papers_op())
    )


@dg.job(
    name="ingest_gero_papers",
    description=(
        "Ingest the gerotranscendence papers, run every GenericChunkExtractionWorkflow "
        "pipeline (causes / how / when / where / effects), and embed the resulting "
        "ExtractedItem texts so they can be searched."
    ),
)
def ingest_gero_papers_job() -> None:
    embed_extracted_items_op(
        start=run_gero_extractions_op(start=ingest_gero_papers_op())
    )


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
                    normalize_paper_paths_job,
                ],
                sensors=[],
            )
        )
