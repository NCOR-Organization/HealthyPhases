import dagster as dg
from naas_abi_core.orchestrations.DagsterOrchestration import DagsterOrchestration


import os
from glob import glob

from phases.workflows.PapersIngestionWorkflow.PapersIngestionWorkflow import (
    PapersIngestionWorkflow,
    PapersIngestionWorkflowConfiguration,
    PapersIngestionWorkflowParameters,
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


@dg.job(
    name="ingest_solitude_papers",
    description=(
        "Manually trigger ingestion of the solitude PMC papers "
        "(abi/src/phases/papers/solitude/pmc/*.pdf) through PapersIngestionWorkflow."
    ),
)
def ingest_solitude_papers_job() -> None:
    ingest_solitude_papers_op()


class PhasesOrchestration(DagsterOrchestration):

    @classmethod
    def New(cls) -> "PhasesOrchestration":
        return cls(
            definitions=dg.Definitions(
                assets=[],
                schedules=[],
                jobs=[ingest_solitude_papers_job],
                sensors=[],
            )
        )
