# Archived workflows

Deprecated / not part of the active phase-one or phase-two pipelines. Kept for reference.
These were the earlier **Axioms** and **Labels** ingestion experiments plus the
orchestration that chained them.

They are **not** imported by
[`orchestrations/PhasesOrchestration.py`](../../orchestrations/PhasesOrchestration.py)
(the active entrypoint). The only real cross-references are inside
`MainIngestionOrchestration` (below), whose imports were rewritten to
`phases.workflows.archive.<Name>` when moved here.

`workflows/` uses PEP 420 namespace packages (no `__init__.py`), so this `archive/`
directory needs none either.

| Workflow | What it did |
| --- | --- |
| [`AxiomsWorkflow`](AxiomsWorkflow/) | Read document chunks from the triple store and extracted axioms (logical sentences) from them. |
| [`AxiomsEmbeddingWorkflow`](AxiomsEmbeddingWorkflow/) | Read extracted axioms and computed vector embeddings for them. |
| [`AxiomsSearchWorkflow`](AxiomsSearchWorkflow/) | Embedded a user prompt and searched extracted axioms by vector similarity. |
| [`AxiomsCrossPaperSimilarityWorkflow`](AxiomsCrossPaperSimilarityWorkflow/) | Analyzed similar axioms across different paper paths. |
| [`LabelsWorkflow`](LabelsWorkflow/) | Read document chunks and extracted labels from them. |
| [`LabelsEmbeddingWorkflow`](LabelsEmbeddingWorkflow/) | Read extracted labels and computed vector embeddings for them. |
| [`LabelsConsolidationWorkflow`](LabelsConsolidationWorkflow/) | Consolidated extracted labels against their source chunks (no graph writes). |
| [`LabelsDefinitionRefinementWorkflow`](LabelsDefinitionRefinementWorkflow/) | Iteratively refined label definitions from representative labels (no graph writes). |
| [`LabelAxiomEmergenceWorkflow`](LabelAxiomEmergenceWorkflow/) | Inferred directed concept emergence from labels and axioms via SPARQL. |
| [`MainIngestionOrchestration`](MainIngestionOrchestration/) | Orchestrated the Axioms/Labels ingestion workflows above in order (plus `PapersIngestionWorkflow`, which stays active). |
| [`SolitudeassessmentinstrumentsandtermsWorkflow`](SolitudeassessmentinstrumentsandtermsWorkflow/) | Matched questionnaire rows against axiom vectors from a CSV `Questionnaire` column. |
