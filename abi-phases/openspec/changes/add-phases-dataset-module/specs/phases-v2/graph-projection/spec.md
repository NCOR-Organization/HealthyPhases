## Purpose

Publishes the pipeline's datasets as RDF in the triple store so the Composer and other graph tools can query papers, chunks and extracted items, while keeping the datasets as the system of record.

## ADDED Requirements

### Requirement: Projection targets dedicated named graphs

The module SHALL write its triples only into named graphs reserved for it. It SHALL NOT write into, modify, or remove triples from the named graphs used by the existing phases module.

#### Scenario: Both modules are running

- **WHEN** this module projects its datasets while the existing phases module also has data in the triple store
- **THEN** the existing module's named graphs are unchanged, and this module's triples are queryable in their own named graphs

#### Scenario: Composer queries the new graphs

- **WHEN** a Composer query targets this module's named graphs
- **THEN** it resolves papers, chunks, extractions and extracted items projected from the datasets

### Requirement: Projection is derived from the datasets

Every triple the module writes SHALL be derivable from rows in its datasets. The triple store SHALL be treatable as a rebuildable projection, not as a source of truth.

#### Scenario: The graph is rebuilt from scratch

- **WHEN** this module's named graphs are cleared and projection is run again over unchanged datasets
- **THEN** the resulting graphs are equivalent to what they held before

### Requirement: Projection is idempotent and incremental

Projection SHALL be safe to run repeatedly. Re-running SHALL NOT duplicate triples, and SHALL only do work for dataset rows that have not yet been projected.

#### Scenario: Projection runs twice with no new data

- **WHEN** projection runs a second time and no dataset rows have been added since
- **THEN** the named graphs are unchanged and no duplicate triples are created

#### Scenario: New extractions arrive

- **WHEN** new extractions are recorded and projection runs again
- **THEN** only the new rows are projected, and the previously projected triples are untouched

#### Scenario: Projection is interrupted

- **WHEN** a projection run is interrupted partway and is started again
- **THEN** it completes the outstanding rows without duplicating what it already wrote

### Requirement: Provenance is preserved in the graph

Projected extraction triples SHALL carry the chunk, model and prompt version they came from, so a claim in the graph can be traced back to the exact chunk, model and prompt text that produced it.

#### Scenario: Tracing a projected claim

- **WHEN** a query resolves an extracted item in the graph
- **THEN** it can follow that item to its chunk, its paper, the model used, and the prompt version used

### Requirement: A projection run reads one coherent instant

A projection run SHALL read every dataset it draws from at a single, consistent point in time, so that a write landing mid-run cannot produce a projection that mixes state from before and after it.

#### Scenario: A write lands mid-run

- **WHEN** new extractions and their items are recorded while a projection run is in progress
- **THEN** that run projects only the state it started from, and the new rows are projected by the next run

#### Scenario: Related rows are never half-projected

- **WHEN** a projection run reads an extraction and the items belonging to it
- **THEN** it never observes the extraction without its items, or the items without their extraction
