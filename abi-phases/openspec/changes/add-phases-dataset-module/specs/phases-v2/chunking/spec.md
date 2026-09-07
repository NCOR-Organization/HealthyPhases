## Purpose

Splits paper text into the units that extraction actually runs against, while allowing several chunking mechanisms to coexist over the same corpus so their results can be compared rather than overwritten.

## ADDED Requirements

### Requirement: Chunking mechanisms are declared in code and identified by content

The module SHALL declare its chunking mechanisms in code. Each mechanism SHALL have a stable `chunker_id` derived from its name, its version and its parameters, so that changing a parameter yields a new `chunker_id` rather than redefining an existing one.

Declared mechanisms SHALL be recorded in a `chunkers` dataset carrying the `chunker_id`, the name, the version, the parameters, and the time it was registered.

#### Scenario: Module starts with a declared chunker

- **WHEN** the module starts and a chunking mechanism is declared in code
- **THEN** a row for its `chunker_id` exists in the `chunkers` dataset

#### Scenario: A chunker parameter changes

- **WHEN** a declared chunker's parameters change and the module starts again
- **THEN** a new `chunker_id` is registered, and the previous `chunker_id` and every chunk produced under it remain intact

#### Scenario: Module restarts with no changes

- **WHEN** the module starts again with unchanged chunker declarations
- **THEN** the `chunkers` dataset still holds exactly one row per declared mechanism

### Requirement: Chunks dataset

Chunks SHALL be recorded in a `chunks` dataset. Each row SHALL carry a `chunk_id`, the `paper_id` it came from, the `chunker_id` that produced it, its position within the paper, its text, and its character offsets in the source text.

`chunk_id` SHALL be derived from the paper, the chunker and the position, so the same chunk is never recorded twice.

#### Scenario: A paper is chunked

- **WHEN** a paper is chunked with a given mechanism
- **THEN** one row per chunk is recorded, each referencing that paper and that chunker

#### Scenario: The same paper is chunked by two mechanisms

- **WHEN** a paper is chunked by two different mechanisms
- **THEN** both sets of chunks exist side by side, each attributable to its own `chunker_id`, and neither replaces the other

#### Scenario: Re-running the same chunker on the same paper

- **WHEN** chunking runs again for a paper and chunker pair that has already been chunked
- **THEN** the chunk rows for that pair are unchanged and not duplicated

### Requirement: Chunking is selectable per run

A caller SHALL be able to run chunking for a chosen mechanism over a chosen set of papers, rather than always over the whole corpus.

#### Scenario: Chunking a subset

- **WHEN** a caller requests chunking with one mechanism for a named subset of papers
- **THEN** only those papers are chunked, and only with that mechanism
