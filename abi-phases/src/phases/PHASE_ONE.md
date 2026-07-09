# Phase One — Paper → Triples Pipeline

**Purpose:** turn research papers into correctly-scoped triples in the Nexus graphs
(ingest → extract → embed).

## Workflows (active — stay in place)

1. **Ingest.** [`workflows/PapersIngestionWorkflow/`](workflows/PapersIngestionWorkflow/)
   — PDFs → `Chunk`s in the papers graph.
   - [`PapersIngestionWorkflow.py`](workflows/PapersIngestionWorkflow/PapersIngestionWorkflow.py)
   - [`normalize_paths_migration.py`](workflows/PapersIngestionWorkflow/normalize_paths_migration.py)
   - [`run_solitude.py`](workflows/PapersIngestionWorkflow/run_solitude.py)
2. **Extract.** [`workflows/GenericChunkExtractionWorkflow/`](workflows/GenericChunkExtractionWorkflow/)
   — chunks → `ExtractedItem`s in the extractions graph.
   - [`GenericChunkExtractionWorkflow.py`](workflows/GenericChunkExtractionWorkflow/GenericChunkExtractionWorkflow.py)
   - [`run_extraction.py`](workflows/GenericChunkExtractionWorkflow/run_extraction.py) — CLI entry
   - [`prompts/`](workflows/GenericChunkExtractionWorkflow/prompts/) — extraction prompt templates
     (`logical_sentences.txt`, `solitude_what.txt`, `solitude_causes.txt`,
     `solitude_effects.txt`, `solitude_how.txt`, `solitude_when.txt`, `solitude_where.txt`)
3. **Embed.** [`workflows/ExtractedItemsEmbeddingWorkflow/`](workflows/ExtractedItemsEmbeddingWorkflow/)
   — embeds the extracted items.
   - [`ExtractedItemsEmbeddingWorkflow.py`](workflows/ExtractedItemsEmbeddingWorkflow/ExtractedItemsEmbeddingWorkflow.py)

## Ontology (shared `ontologies/` module)

- [`ontologies/documents.ttl`](ontologies/documents.ttl) / [`ontologies/documents.py`](ontologies/documents.py)
  — paper/chunk/extraction model:
  `PDFPaperFile`, `Chunk`, `ExtractedItem`, `Extraction`, `chunk_of`, `extracted_from_chunk`.
- Foundation: [`ontologies/bfo_core.ttl`](ontologies/bfo_core.ttl) /
  [`ontologies/bfo_core.py`](ontologies/bfo_core.py) — shared across phases.

## Named graphs

- `http://ontology.naas.ai/graph/phases/papers` — `PDFPaperFile`, `Chunk`, `chunk_of`.
- `http://ontology.naas.ai/graph/phases/extractions` — `ExtractedItem`, `Extraction`,
  `extracted_from_chunk`.

The extraction chain **crosses the graph boundary at hop 1**: `ExtractedItem`
(extractions graph) → `extracted_from_chunk` → `Chunk` (papers graph).

## Orchestration entrypoint

[`orchestrations/PhasesOrchestration.py`](orchestrations/PhasesOrchestration.py)

## Paper it feeds

<!-- TODO: link the paper/draft this phase produces triples for. -->

## Archived / not in use

The `Axioms*` and `Labels*` workflows are deprecated and have been moved to
[`workflows/archive/`](workflows/archive/README.md) — see that README (and Part B of
this phase's archive change). They are not part of the active phase-one pipeline.
