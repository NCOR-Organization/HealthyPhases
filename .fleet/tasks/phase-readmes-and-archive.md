# Task Brief — Per-phase READMEs + archive unused workflows

> Referenced by MISSION Backlog. One agent, one run, on a `fleet/` worktree branch.
> Decision: do NOT create phase modules. Files stay where they are. Phase membership is
> expressed by **per-phase README manifests** that link to the real files. Separately,
> the genuinely-unused workflows move into `workflows/archive/` to declutter.

## Why this shape
A reviewer of a phase-one (or phase-two) paper needs to find *everything that phase uses*
— workflows AND ontology AND graphs — in one place. Physically splitting the code fails
here because the ontology is one unified BFO-aligned artifact (the merged
`phases.ttl`/`phases.owl` + `bfo_core`) that must stay whole. A README manifest gives the
"phase view" without fragmenting anything. Zero import churn for the phase files.

---

## Part A — Per-phase README manifests (the main deliverable)

Create two manifests at the `phases` package root (adjust location if a better home
exists): `abi-phases/src/phases/PHASE_ONE.md` and `abi-phases/src/phases/PHASE_TWO.md`.
Use **repo-relative, clickable paths**. Each must cover: purpose · workflows (linked) ·
ontology files + the exact terms/IRIs (linked) · named graph(s) · orchestration entrypoint
· how to run · the paper it feeds. Verify every path and term against the code before
writing it — this is a research artifact, it must be accurate.

### PHASE_ONE.md — generic paper → triples pipeline (ingest → extract → embed)
- **Workflows** (all stay in place, do not move):
  - `src/phases/workflows/PapersIngestionWorkflow/` — PDFs → `Chunk`s in the papers graph
  - `src/phases/workflows/GenericChunkExtractionWorkflow/` (+ `run_extraction.py`,
    `prompts/`) — chunks → `ExtractedItem`s in the extractions graph
  - `src/phases/workflows/ExtractedItemsEmbeddingWorkflow/` — embeds extracted items
- **Ontology** (stays in the shared `ontologies/` module):
  - `src/phases/ontologies/documents.ttl` / `documents.py` — the paper/chunk/extraction
    model: `PDFPaperFile`, `Chunk`, `ExtractedItem`, `Extraction`, `chunk_of`,
    `extracted_from_chunk`
  - Foundation: `src/phases/ontologies/bfo_core.*` (shared, do not duplicate)
- **Named graphs:** `http://ontology.naas.ai/graph/phases/papers` (PDFPaperFile, Chunk,
  chunk_of) and `…/graph/phases/extractions` (ExtractedItem, Extraction,
  extracted_from_chunk). The extraction chain crosses the graph boundary at hop 1.
- **Orchestration entrypoint:** `src/phases/orchestrations/PhasesOrchestration.py`
- **Paper it feeds:** <fill in — link the paper/draft this phase supports>

### PHASE_TWO.md — probabilistic process-disposition extraction (builds on phase one)
- **Workflow:** `src/phases/workflows/ProcessDispositionExtractionWorkflow/`
  (+ `prompts/probabilistic_processes.txt`)
- **Ontology** (stays in shared `ontologies/`):
  - Disposition classes under
    `src/phases/ontologies/classes/purl_obolibrary_org/obo/phases/`:
    `ProbabilitymodulatingDisposition.py`, `IncreaseprobabilityDisposition.py`,
    `DecreaseprobabilityDisposition.py`, `NoeffectProbabilityDisposition.py`
  - Probability relations added in `src/phases/ontologies/relations.py`
- **Depends on phase one:** consumes phase-one `ExtractedItem`s / extractions graph.
- **Orchestration entrypoint:** `src/phases/orchestrations/PhasesOrchestration.py`
- **Paper it feeds:** <fill in>

> Optional: a short `## Archived / not in use` pointer at the bottom of each, or a separate
> note, so a reader knows the Axioms/Labels workflows are deprecated (see Part B).

---

## Part B — Move unused workflows into `workflows/archive/`

Move these 11 dirs with `git mv` (history preserved) into
`abi-phases/src/phases/workflows/archive/`. Leave phase-one/two workflows untouched.

```
AxiomsCrossPaperSimilarityWorkflow   AxiomsEmbeddingWorkflow
AxiomsSearchWorkflow                 AxiomsWorkflow
LabelAxiomEmergenceWorkflow          LabelsConsolidationWorkflow
LabelsDefinitionRefinementWorkflow   LabelsEmbeddingWorkflow
LabelsWorkflow                       MainIngestionOrchestration
SolitudeassessmentinstrumentsandtermsWorkflow
```

`workflows/` has no `__init__.py` (PEP 420 namespace packages) — the new `archive/` dir
needs none either.

**Import sweep (self-contained — confirmed blast radius):** nothing *active* imports any of
these. The only real imports are inside `MainIngestionOrchestration.py` (it imports the
Axioms/Labels workflows) plus any self-imports within the moved dirs. Do a repo-wide
rewrite over `abi-phases/src/` (`.py` only; NOT `.abi/`, NOT `.claude/worktrees/`):
`phases.workflows.<ArchivedName>` → `phases.workflows.archive.<ArchivedName>` for each of
the 11 names above.
- **Do NOT** rewrite `phases.workflows.PapersIngestionWorkflow` — PapersIngestion stays put,
  so `MainIngestionOrchestration`'s import of it remains valid unchanged.
- `PhasesOrchestration.py` imports none of the archived workflows → leave it alone.
- Add `workflows/archive/README.md` listing each archived workflow with a one-line note on
  what it did / why it's parked.

---

## Verify
From `abi-phases/`:
1. `uv sync`
2. `uv run python -c "import phases.orchestrations.PhasesOrchestration"` → no ImportError
   (proves the active pipeline is intact).
3. `uv run python -c "import phases.workflows.archive.MainIngestionOrchestration.MainIngestionOrchestration"`
   → resolves (proves the archive package + its rewritten imports work).
4. `grep -rn "phases\.workflows\.\(Axioms\|Labels\|MainIngestion\|Solitude\)" src` returns
   nothing that still points at the pre-move path (sweep complete).
5. `uv run pytest` (note any pre-existing unrelated failures).

## Done when
- `PHASE_ONE.md` and `PHASE_TWO.md` exist, every linked path/term verified accurate, paper
  links filled in (or marked TODO if the paper doesn't exist yet).
- The 11 workflows are under `workflows/archive/` (git mv), archive README written, import
  sweep complete, verify steps 2–5 pass.
- JOURNAL entry written (what moved, what the manifests cover, verification result). PR opened.
