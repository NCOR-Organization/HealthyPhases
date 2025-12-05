# ABI – Healthy Phases

This package hosts the ABI (Artificial Business Intelligence) stack dedicated to the Healthy Phases project. It wires custom agents, models, and ontologies into the [naas-abi](https://pypi.org/project/naas-abi) runtime so that the HealthyPhases research team can prototype and publish assistants tailored to solitude and gerotranscendence studies.

## Project Layout

- `pyproject.toml` – Python 3.12 project definition managed through `uv`.
- `config.yaml` / `config.yaml` – production vs. local configuration passed to the ABI engine.
- `abi_phases/phases` – primary module exposing the custom `ABIModule`, Google Gemini model wrapper, ontology, and the ELO agent.
- `abi_phases/google_gemini_2_0_flash` – self-contained model/agent example for Gemini 2.0 Flash.
- `Makefile` – shortcuts the research & engineering team uses to chat with or serve the ABI.
- `Dockerfile` – container definition for packaging/running the API on port `9879`.
- `uv.lock` – frozen dependency graph.

## Prerequisites

- Python `3.12` (enforced via `.python-version`; Dockerfile currently pins 3.11, update if you rely on features that require 3.12).
- [`uv`](https://github.com/astral-sh/uv) package manager (`pip install uv` or use the bundled install inside Docker).
- Access to Naas and LLM provider credentials (see below).

## Configuration & Secrets

Runtime settings live in `config.yaml`. This file defines:

- workspace metadata (`deploy.*`)
- API surface (title, branding assets, CORS origins)
- enabled modules (`naas_abi`, PubMed application, `abi_phases.phases`, etc.)
- service adapters (dotenv secrets, filesystem object/triple stores, Qdrant vector store)

Secrets referenced in the configs must be provided through `.env` (loaded via the dotenv adapter) or the Naas secret manager:

| Variable | Purpose |
| --- | --- |
| `NAAS_API_KEY` | Required to interact with the target Naas workspace. |
| `OPENAI_API_KEY` | Used by `naas_abi` and `naas_abi_marketplace.ai.chatgpt` modules. |
| `GOOGLE_API_KEY` | Consumed by the Gemini 2.0 Flash model in `abi_phases.phases`. |

Remember to add any branding assets referenced in `config*.yaml` (`assets/logo.png`, `assets/favicon.ico`).

## Running & Chatting

### Make targets (recommended)

```bash
make api   # runs uv run python -m naas_abi_core.apps.api.api
make chat  # opens an interactive chat with the ELO agent
```

Both targets rely on the dependencies installed through `uv sync` and automatically use `config.yaml`.

### Manual uv invocation

```bash
uv run python -m naas_abi_core.apps.api.api
```

Use this form when you need to pass additional CLI flags or a different config file.

## Agents, Models, and Ontologies

- **ELO Agent (`abi_phases/phases/agents/ELOAgent.py`)**  
  - Ontology-aware IntentAgent tailored to solitude and gerotranscendence research.  
  - Uses the local Gemini chat model, enriched with the ontology in `abi_phases/phases/ontologies/phases.ttl`.  
  - Routes publication-related intents to the PubMed marketplace agent.

- **Gemini 2.0 Flash Model (`abi_phases/phases/models/google_gemini_2_0_flash.py`)**  
  - Wraps `langchain_google_genai.ChatGoogleGenerativeAI`.  
  - Pulls the Google API key from the module configuration for consistent secret handling.

- **Example standalone model/agent (`abi_phases/google_gemini_2_0_flash/`)**  
  - Shows how to package a model with tests and a thin Agent wrapper for reuse.

## Publishing & Deployment

- `auto_publish` toggles whether agents are automatically pushed to the configured Naas workspace. Update `exclude_agents` or `default_agent` as new assistants are added.
- `deploy.workspace_id`, `deploy.space_name`, and `deploy.naas_api_key` in `config.yaml` should be kept in sync with the destination workspace.
- The included Docker image plus `config.yaml` can be wired into CI/CD or the GitHub Actions workflow defined in `.github/workflows/deploy.yaml`.

## Testing

Use `pytest` through uv:

```bash
uv run pytest abi_phases
```

The sample test in `abi_phases/google_gemini_2_0_flash/models/google_gemini_2_0_flash_test.py` exercises the Gemini model; expand this suite as you add agents or modules.

## Next Steps

- Extend `abi_phases/phases/agents` with additional Healthy Phases assistants.
- Update `config*.yaml` when introducing new Naas modules or storage adapters.
- Keep the Docker image aligned with the Python version declared in `pyproject.toml`.
