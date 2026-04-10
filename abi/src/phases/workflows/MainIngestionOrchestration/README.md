# Main Ingestion Orchestration

A workflow that orchestrates all ingestion workflows in the correct order with proper parallelization.

## Workflow Chain

```
PapersIngestionWorkflow
        ↓
   ┌────┴────┐
   ↓         ↓
Labels    Axioms
Workflow  Workflow       ← PARALLEL
   ↓         ↓
Labels    Axioms
Embedding Embedding      ← PARALLEL
   ↓         ↓
   └────┬────┘
        ↓
LabelsConsolidationWorkflow
        ↓
LabelsDefinitionRefinementWorkflow
        ↓
LabelAxiomEmergenceWorkflow
```

## Features

- **Parallel execution**: Labels and Axioms extraction run in parallel (threaded)
- **Parallel embedding**: Labels and Axioms embedding run in parallel
- **Idempotent**: Each sub-workflow skips already-processed data
- **Timestamped outputs**: Each run creates its own output directory
- **Error handling**: Warnings logged to file, pipeline continues
- **Skip flags**: Can skip entire phases (extraction, embedding, analysis)

## Usage

### Full pipeline
```bash
cd abi
uv run abi run script abi_phases/phases/workflows/MainIngestionOrchestration/MainIngestionOrchestration.py
```

### With options
```bash
# Force reprocessing
uv run abi run script abi_phases/phases/workflows/MainIngestionOrchestration/MainIngestionOrchestration.py --force

# More workers for LLM calls
uv run abi run script abi_phases/phases/workflows/MainIngestionOrchestration/MainIngestionOrchestration.py --workers 20

# Skip certain phases
uv run abi run script abi_phases/phases/workflows/MainIngestionOrchestration/MainIngestionOrchestration.py --skip-extraction
uv run abi run script abi_phases/phases/workflows/MainIngestionOrchestration/MainIngestionOrchestration.py --skip-embedding
uv run abi run script abi_phases/phases/workflows/MainIngestionOrchestration/MainIngestionOrchestration.py --skip-analysis

# Custom paths
uv run abi run script abi_phases/phases/workflows/MainIngestionOrchestration/MainIngestionOrchestration.py --papers-path /path/to/papers --ontology-path /path/to/ontology.owl
```

### Dry run (audit mode)
```bash
uv run abi run script abi_phases/phases/workflows/MainIngestionOrchestration/MainIngestionOrchestration.py --dry-run
```

## Output

Each run creates:
```
outputs/run_YYYYMMDD_HHMMSS/
├── orchestration.log       # Full log with warnings
├── labels_consolidation/   # Consolidation outputs
├── labels_definition_refinement/  # Refinement outputs
└── label_axiom_emergence/  # Emergence outputs
```

## Re-running

Re-running the pipeline is safe:
- Papers already ingested are skipped
- Chunks already labeled are skipped (unless `--force`)
- Similar logic applies to all sub-workflows
- Warnings from previous runs are not tracked (each run is independent)
