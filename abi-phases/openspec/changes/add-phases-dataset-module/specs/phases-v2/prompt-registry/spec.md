## Purpose

Keeps prompt templates in code while giving every version of a template a durable identity, so that editing a prompt produces a new version instead of invalidating or silently rewriting everything already extracted with the old one.

## ADDED Requirements

### Requirement: Prompt templates are declared in code and persisted at module start

The module SHALL declare its prompt templates in code. When the module starts, it SHALL record every declared template in a `prompts` dataset.

#### Scenario: Module starts

- **WHEN** the module starts with prompt templates declared in code
- **THEN** each declared template has a row in the `prompts` dataset

#### Scenario: Dataset does not yet exist

- **WHEN** the module starts and the `prompts` dataset has not been created
- **THEN** the dataset is created and the declared templates are recorded

### Requirement: Prompt versions are identified by content hash

Each prompt row SHALL carry a `prompt_id` derived from the template's name and a hash of its text. Editing a template's text SHALL produce a new `prompt_id`.

Prompt rows SHALL never be modified or removed. Each row SHALL carry the template name, the content hash, the full template text, the expected output key, and the time it was registered.

#### Scenario: A template's text is edited

- **WHEN** a declared template's text changes and the module starts again
- **THEN** a new row with a new `prompt_id` is recorded, and the row for the previous `prompt_id` is left untouched

#### Scenario: Module restarts with unchanged templates

- **WHEN** the module starts again and no template text has changed
- **THEN** the dataset still holds exactly one row per declared template version

#### Scenario: Prior work stays attributable

- **WHEN** extractions exist that were produced with an earlier `prompt_id` and the template is later edited
- **THEN** those extractions remain valid and still resolve to the exact template text they were produced with

### Requirement: Prompt templates declare their placeholders

A template SHALL declare the placeholder it fills with chunk text, and the module SHALL reject a declared template that omits it.

#### Scenario: A template is missing its chunk placeholder

- **WHEN** the module starts with a declared template that has no chunk-text placeholder
- **THEN** module start fails with an error naming the offending template, and no row is recorded for it
