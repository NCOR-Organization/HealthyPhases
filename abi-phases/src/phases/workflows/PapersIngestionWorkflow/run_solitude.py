"""Run PapersIngestionWorkflow scoped to the solitude/pmc papers only."""
import os
from glob import glob

from phases.workflows.PapersIngestionWorkflow.PapersIngestionWorkflow import (
    PapersIngestionWorkflow,
    PapersIngestionWorkflowConfiguration,
    PapersIngestionWorkflowParameters,
)

PAPERS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "papers", "solitude", "pmc"
)
ONTOLOGY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "ontologies", "phases.owl"
)


def main() -> None:
    paths = sorted(glob(os.path.join(PAPERS_DIR, "*.pdf")))
    print(f"Ingesting {len(paths)} solitude/pmc papers")

    workflow = PapersIngestionWorkflow(PapersIngestionWorkflowConfiguration())
    workflow.run(
        PapersIngestionWorkflowParameters(
            paths=paths,
            ontology_path=os.path.abspath(ONTOLOGY_PATH),
        )
    )


if __name__ == "__main__":
    main()
