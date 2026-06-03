# Research Log: PHASES Workflows and Ontologies

## Context and objective

This document logs a first-pass technical and methodological analysis of the PHASES extraction stack, focusing on:

- `abi/abi_phases/phases/workflows/`
- `abi/abi_phases/phases/ontologies/`

The goal is to consolidate implementation-level evidence into research-ready notes for a potential paper on ontology-guided LLM extraction, semantic normalization, and cross-document synthesis in solitude-related literature.

---

## High-level system view

### Core architecture

The codebase implements a hybrid symbolic + neural pipeline:

1. **Document ingestion and chunking** into RDF + vector store.
2. **LLM extraction** of two structured artifact types from chunks:
   - topical labels
   - natural-language axioms
3. **Embedding/indexing** of extracted artifacts in dedicated collections.
4. **Retrieval/analysis workflows** (semantic search, cross-paper similarity, CSV projection).
5. **Iterative refinement workflows** to consolidate labels and draft definitions.

### Data backends

- **Triple store**: symbolic persistence, provenance, queryability (SPARQL).
- **Vector store**: approximate semantic retrieval over chunk/label/axiom embeddings.
- **Object storage**: markdownized paper content.

This dual-storage strategy is central: provenance and constraints are explicit in RDF, while semantic similarity is handled by vectors.

---

## Workflow inventory and roles

## 1) `PapersIngestionWorkflow`

File: `abi/abi_phases/phases/workflows/PapersIngestionWorkflow/PapersIngestionWorkflow.py`

### What it does

- Converts PDFs to Markdown (`pymupdf4llm`), stores in object storage.
- Chunks and embeds markdown text (`embed_text`), stores:
  - `phases-doc:PDFPaperFile`
  - `phases-doc:Chunk`
  - chunk vectors in `papers` collection.
- Detects ontology term occurrences in chunks via:
  - lexical matching on `skos:prefLabel`
  - embedding similarity on `skos:definition`
- Persists `LexicalOccurrence` and `EmbeddingOccurrence` instances.

### Research relevance

- Establishes the **evidence graph** linking ontology entities to concrete textual contexts.
- Provides early-stage alignment between curated ontology semantics and literature text.

### Notes

- Uses duplicate checks for existing `PDFPaperFile` and pre-existing occurrence links.
- Current lexical matching uses `CONTAINS`, which is interpretable but may overmatch without boundary checks.

---

## 2) `AxiomsWorkflow`

File: `abi/abi_phases/phases/workflows/AxiomsWorkflow/AxiomsWorkflow.py`

### What it does

- Reads candidate chunks from triple store.
- Prompts LLM to output strict JSON: `{"axioms": ["..."]}`.
- Normalizes and deduplicates extracted axioms.
- Persists each axiom as `phases-ax:ExtractedAxiom` with:
  - text
  - hash
  - ordinal position in extraction result
  - chunk provenance
  - model/prompt metadata
  - creation timestamp

### Research relevance

- Operationalizes "axiom mining" as reproducible extraction with provenance.
- Supports analysis of emergent rule-like regularities from literature chunks.

### Notes

- Includes dry-run audit mode with optional turtle preview of would-be inserts.
- Parallel extraction is supported (`ThreadPoolExecutor`).

---

## 3) `AxiomsEmbeddingWorkflow`

File: `abi/abi_phases/phases/workflows/AxiomsEmbeddingWorkflow/AxiomsEmbeddingWorkflow.py`

### What it does

- Queries extracted axioms from RDF.
- Embeds `axiom_text` with `text-embedding-3-large`.
- Upserts into vector collection (default `phases_axioms`).
- Stores provenance-rich metadata in vector records.

### Research relevance

- Enables semantic retrieval and clustering of rule-like statements.
- Decouples extraction from downstream similarity analytics.

---

## 4) `AxiomsSearchWorkflow`

File: `abi/abi_phases/phases/workflows/AxiomsSearchWorkflow/AxiomsSearchWorkflow.py`

### What it does

- Embeds free-text query prompt.
- Searches axioms collection with configurable top-k and threshold.
- Returns match score + provenance fields (path, chunk, IDs).

### Research relevance

- Human-in-the-loop exploration interface for concept probing.
- Useful for qualitative validation of extraction usefulness.

---

## 5) `AxiomsCrossPaperSimilarityWorkflow`

File: `abi/abi_phases/phases/workflows/AxiomsCrossPaperSimilarityWorkflow/AxiomsCrossPaperSimilarityWorkflow.py`

### What it does

- For each source axiom, performs vector search.
- Filters out self-match and same-paper matches.
- Keeps only cross-paper neighbors above score threshold.
- Exports rich CSV for analysis.

### Research relevance

- Directly supports a paper-level claim: whether conceptual regularities recur across independent sources.
- Natural basis for reporting cross-document convergence metrics.

---

## 6) `LabelsWorkflow`

File: `abi/abi_phases/phases/workflows/LabelsWorkflow/LabelsWorkflow.py`

### What it does

- Reads chunks from triple store (optionally filtered by path).
- By default, restricts processing to paths containing `solitude` or `paid`.
- Prompts LLM for strict JSON labels: `{"labels": ["..."]}`.
- Cleans and deduplicates labels (lowercasing, punctuation trimming, max words).
- Persists `phases-label:ExtractedLabel` with provenance + generation metadata.

### Research relevance

- Produces a controlled, reusable topical layer for frequency and taxonomy analyses.
- Captures prompt/model provenance needed for reproducibility sections.

### Notes

- Includes dry-run mode and optional triple preview.
- Supports parallel extraction workers.

---

## 7) Label export utilities

Files:

- `abi/abi_phases/phases/workflows/LabelsWorkflow/ExportLabelCountsCSV.py`
- `abi/abi_phases/phases/workflows/LabelsWorkflow/ExportLabelCountsByPaperCSV.py`
- `abi/abi_phases/phases/workflows/LabelsWorkflow/ExportRepresentativeLabelChunksCSV.py`

### What they do

- Produce publication-friendly CSVs for:
  - global label frequencies and paper coverage
  - per-paper breakdown with global aggregates
  - representative chunk text evidence for labels above paper-coverage threshold

### Research relevance

- These scripts are practical bridges from RDF internals to analysis tables and appendices.

---

## 8) `LabelsConsolidationWorkflow`

File: `abi/abi_phases/phases/workflows/LabelsConsolidationWorkflow/LabelsConsolidationWorkflow.py`

### What it does

- Loads extracted labels + source context.
- Applies deterministic normalization (case, punctuation, separators).
- Optionally applies semantic clustering using embeddings with:
  - auto-merge threshold (default `0.92`)
  - review threshold (default `0.85`)
- Selects cluster representatives via frequency/conciseness tie-break.
- Writes outputs for review and next steps:
  - `canonical_labels.csv`
  - `label_merge_map.csv`
  - `semantic_review_pairs.csv`
  - `canonical_labels_for_definitions.json`

### Research relevance

- Implements a transparent normalization pipeline balancing automation and expert review.
- Provides explicit intermediate artifacts suitable for methods section and supplementary material.

### Important design choice

- No graph writes: this preserves a separation between exploratory consolidation and authoritative ontology updates.

---

## 9) `LabelsDefinitionRefinementWorkflow`

File: `abi/abi_phases/phases/workflows/LabelsDefinitionRefinementWorkflow/LabelsDefinitionRefinementWorkflow.py`

### What it does

- Selects labels with sufficient cross-paper support (`min_paper_count`).
- Samples chunk evidence with paper-balancing constraints.
- Iteratively refines a definition state per label chunk-by-chunk.
- Enforces strict JSON state updates (definition, criteria, confidence, verdict).
- Exports:
  - full refined definitions JSON
  - summary CSV
  - per-step history JSONL

### Research relevance

- Encodes a traceable "definition evolution" process rather than one-shot generation.
- Produces auditable revision histories aligned with scientific transparency goals.

### Important design choice

- Also no graph writes: definitions remain drafts until curated.

---

## 10) `SolitudeAssessmentInstrumentsAndTermsWorkflow`

File: `abi/abi_phases/phases/workflows/SolitudeassessmentinstrumentsandtermsWorkflow/SolitudeassessmentinstrumentsandtermsWorkflow.py`

### What it does

- Reads CSV rows with questionnaire/instrument terms.
- Embeds each term and retrieves top-k axioms.
- Writes expanded CSV with ranking, score, and provenance metadata.

### Research relevance

- Demonstrates task-oriented reuse of extracted knowledge for instrument-term alignment.
- Potentially supports translational analyses (literature concepts to practical assessment tools).

---

## Ontology layer assessment

## Modular ontologies

- `documents.ttl`: source files, chunks, lexical/embedding occurrences.
- `labels.ttl`: extracted topical labels.
- `axioms.ttl`: extracted axioms.
- `phases.owl`: broader domain ontology imported for class-level semantics.

Each extraction ontology declares SHACL node shapes, which is important for eventual data-quality validation.

## Python ontology bindings

Files:

- `abi/abi_phases/phases/ontologies/documents.py`
- `abi/abi_phases/phases/ontologies/labels.py`
- `abi/abi_phases/phases/ontologies/axioms.py`

These generated Pydantic classes provide typed construction of RDF entities and graph serialization (`rdf()`), reducing ad-hoc triple assembly.

## Conceptual strengths

- Explicit provenance links (`*_from_chunk`, `source_chunk_id`, path metadata).
- Clear separation between extracted artifacts and source chunks.
- Alignment with BFO class hierarchy (extracted entities as dependent continuants).

---

## End-to-end methodological interpretation

The implemented stack can be interpreted as a multi-stage scientific workflow:

1. **Corpus operationalization**: PDF -> markdown -> chunk graph + vectors.
2. **Ontology-grounded evidence mapping**: lexical/embedding occurrence detection.
3. **LLM-mediated abstraction**: chunk -> labels/axioms.
4. **Semantic indexing**: labels/axioms -> vector collections.
5. **Cross-document synthesis**: similarity and frequency analyses.
6. **Human-curation handoff**: consolidation and iterative definition drafting.

This is not just an extraction pipeline; it is a knowledge-construction protocol with explicit checkpoints and artifacts.

---

## Reproducibility notes for a paper methods section

- Model defaults are explicit in code (e.g., `gpt-5-mini`, `text-embedding-3-large`).
- Prompt versioning is persisted (`prompt_version`).
- Timestamps are persisted (`creation_time`).
- Deterministic IDs/hashes are used for dedupe and cross-store linkage.
- Dry-run modes exist for extraction audit without writes.

Potential reproducibility gap:

- The exact `embed_text` chunking strategy is external to reviewed files and should be documented in detail in the paper.

---

## Potential research questions enabled by this implementation

1. **Cross-paper convergence**: Which extracted axioms recur semantically across independent papers?
2. **Concept stability**: How stable are extracted labels before and after consolidation?
3. **Ontology-text alignment**: Do lexical and embedding occurrences agree in identifying ontology-grounded evidence?
4. **Definition maturation**: How much does iterative refinement alter initial label definitions and confidence?
5. **Instrument linkage**: Can questionnaire terms be systematically connected to literature-derived axioms?

---

## Risks and validity threats to acknowledge

- LLM extraction bias from prompt design and model behavior.
- Lexical `CONTAINS` matching may produce false positives (substring effects).
- Similarity thresholds (0.75/0.85/0.92) are heuristic and may need calibration studies.
- Cross-paper similarity may reflect stylistic overlap, not necessarily conceptual identity.
- Current workflows rely on path-token filters (`solitude`, `paid`) that encode corpus assumptions.

---

## Suggested evaluation plan (paper-oriented)

1. **Gold-sample annotation** for labels/axioms on a stratified chunk subset.
2. **Precision/recall** for lexical and embedding occurrence detection.
3. **Inter-rater agreement** for canonical-label merges and definition adequacy.
4. **Threshold sensitivity analysis** for semantic merge and cross-paper similarity.
5. **Ablation**: deterministic normalization only vs normalization + semantic merge.

---

## Immediate next artifacts to produce

- Methods diagram (pipeline + storage + ontology interactions).
- Data dictionary for all exported CSV/JSON fields.
- Calibration notebook for similarity thresholds.
- Curation protocol for accepting/rejecting consolidated labels and refined definitions.

---

## Closing synthesis

The PHASES workflows in this scope implement a credible research pipeline for ontology-informed literature mining. A key strength is the explicit coupling of provenance-rich RDF artifacts with vector-based semantic retrieval. Another strength is the deliberate non-destructive staging of consolidation and definition refinement outputs, which supports transparent human curation before ontology commitments. With targeted evaluation and calibration, this codebase is already close to supporting a rigorous methods/results narrative for a research paper.
