## Purpose

Declares which AI models the pipeline may run extractions with, and publishes that list so the webapp can present a chooser instead of asking a user to type a model identifier.

## ADDED Requirements

### Requirement: Models are declared in code

The module SHALL declare in code the set of AI models its extractions may use. Each declared model SHALL have a stable identifier, a provider, and the provider's own model identifier.

#### Scenario: A model is declared

- **WHEN** the module starts with a model declared in code
- **THEN** that model is available to the pipeline under its stable identifier

#### Scenario: An extraction names an undeclared model

- **WHEN** a run requests extraction with a model identifier that is not declared
- **THEN** the run fails with an error naming the unknown model, and no extraction rows are written

### Requirement: Declared models are published for the webapp

Declared models SHALL be recorded in a `models` dataset carrying the model identifier, the provider, the provider model identifier, a display name, and the time it was registered, so that a client can list the available models without reading the module's source.

#### Scenario: Webapp lists available models

- **WHEN** a client reads the `models` dataset
- **THEN** it receives every model the pipeline can currently run extractions with

#### Scenario: Module restarts with unchanged declarations

- **WHEN** the module starts again with no change to its model declarations
- **THEN** the dataset still holds exactly one row per declared model

#### Scenario: A model is withdrawn from the declarations

- **WHEN** a model is removed from the code declarations
- **THEN** it is no longer offered for new runs, and extraction rows that reference it remain readable and attributable
