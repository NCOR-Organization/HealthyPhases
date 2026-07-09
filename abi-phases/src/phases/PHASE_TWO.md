# Phase Two — Probabilistic Process-Disposition Extraction

**Purpose:** extract probability-modulating BFO process-disposition triples
(a subject process that *increases / decreases / has no effect on* the probability of a
target process). Builds on phase one.

## Workflow (active — stays in place)

[`workflows/ProcessDispositionExtractionWorkflow/`](workflows/ProcessDispositionExtractionWorkflow/)

- [`ProcessDispositionExtractionWorkflow.py`](workflows/ProcessDispositionExtractionWorkflow/ProcessDispositionExtractionWorkflow.py)
- [`run_extraction.py`](workflows/ProcessDispositionExtractionWorkflow/run_extraction.py) — CLI entry
- [`prompts/probabilistic_processes.txt`](workflows/ProcessDispositionExtractionWorkflow/prompts/probabilistic_processes.txt)

## Ontology (shared `ontologies/` module)

Disposition classes under `ontologies/classes/purl_obolibrary_org/obo/phases/`.
These are phase-two work-in-progress and may be absent from a given checkout —
canonical paths are listed regardless:

- [`ProbabilitymodulatingDisposition.py`](ontologies/classes/purl_obolibrary_org/obo/phases/ProbabilitymodulatingDisposition.py) *(pending commit)*
- [`IncreaseprobabilityDisposition.py`](ontologies/classes/purl_obolibrary_org/obo/phases/IncreaseprobabilityDisposition.py) *(pending commit)*
- [`DecreaseprobabilityDisposition.py`](ontologies/classes/purl_obolibrary_org/obo/phases/DecreaseprobabilityDisposition.py) *(pending commit)*
- [`NoeffectProbabilityDisposition.py`](ontologies/classes/purl_obolibrary_org/obo/phases/NoeffectProbabilityDisposition.py) *(pending commit)*

Probability relations: [`ontologies/relations.py`](ontologies/relations.py) /
[`ontologies/relations.ttl`](ontologies/relations.ttl)
(namespace `http://purl.obolibrary.org/obo/phases/relations.owl#`, e.g.
`ProbabilityModulatingDisposition`, `IncreaseProbabilityDisposition`,
`DecreaseProbabilityDisposition`, `NoEffectProbabilityDisposition`,
`disposition_target_process`).

## Depends on phase one

Consumes phase-one `ExtractedItem`s / the `…/graph/phases/extractions` graph produced by
the [phase-one pipeline](PHASE_ONE.md).

## Orchestration entrypoint

[`orchestrations/PhasesOrchestration.py`](orchestrations/PhasesOrchestration.py)

## Paper it feeds

<!-- TODO: link the paper/draft this phase produces triples for. -->

## Archived / not in use

The `Axioms*` and `Labels*` workflows are deprecated and have been moved to
[`workflows/archive/`](workflows/archive/README.md). They are not part of phase two.
