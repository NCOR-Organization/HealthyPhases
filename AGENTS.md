# AGENTS.md

Guidance for coding agents working in this repository.

## 1) Repository Map

- This repo has two main code areas:
- `./` = Docusaurus website (`src/`, `docs/`, `static/`, `api/`), Node 18.
- `./abi/` = HealthyPhases ABI Python package, managed with `uv`.
- `./abi/abi/` = larger ABI monorepo snapshot with extensive Make targets.

## 2) Cursor/Copilot Rules

- Checked for `.cursor/rules/`, `.cursorrules`, and `.github/copilot-instructions.md`.
- No Cursor or Copilot instruction files are present in this repository.
- If these files are added later, treat them as high-priority local instructions.

## 3) Environment and Tooling

- Node engine for website: `>=18.0.0 <20.0.0`.
- Python for `abi/`: `>=3.12` (see `abi/pyproject.toml`).
- Python for `abi/abi/`: `>=3.10,<4` (see `abi/abi/pyproject.toml`).
- Preferred Python package manager in this repo: `uv`.
- Avoid committing secrets from `.env`, `config.yaml`, `config.*.yaml`.

## 4) Setup Commands

### Website (`./`)

- Install deps: `npm install`
- Run dev server: `npm run start`
- Build production site: `npm run build`
- Serve built site: `npm run serve`
- Clear Docusaurus cache: `npm run clear`
- Wiki dev config: `npm run wiki-dev`
- Wiki build config: `npm run wiki-build`

### ABI package (`./abi`)

- Install/sync deps: `uv sync`
- Chat target: `make chat`
- API target: `make api`
- Run tests: `uv run pytest abi_phases`

### Full ABI workspace (`./abi/abi`)

- Install all deps/extras: `make deps`
- Run default local stack + chat: `make`
- Start API: `make api`
- Run all tests: `make test`
- Run quality checks: `make check`
- Format code: `make fmt`

## 5) Lint / Typecheck / Test Commands

### Primary quality commands (`./abi/abi`)

- Ruff lint: `uvx ruff check libs/naas-abi-core libs/naas-abi-cli libs/naas-abi`
- Ruff format: `uvx ruff format`
- Mypy (core): `cd libs/naas-abi-core && uv sync --all-extras && .venv/bin/mypy -p naas_abi_core --follow-untyped-imports`
- Mypy (cli): `cd libs/naas-abi-cli && uv sync --all-extras && .venv/bin/mypy -p naas_abi_cli --follow-untyped-imports --exclude "naas_abi_cli/cli/new/templates"`
- Mypy (marketplace): `cd libs/naas-abi-marketplace && uv sync --all-extras && uv run mypy -p naas_abi_marketplace --follow-untyped-imports`

### Test commands (`./abi/abi`)

- Run everything: `uv run python -m pytest .`
- Run test folder only: `uv run python -m pytest tests/`
- Run ABI library tests: `uv run python -m pytest lib`
- Run API test file: `uv run python -m pytest libs/naas-abi-core/naas_abi_core/apps/api/api_test.py -v -s`
- Run CI sanity test: `uv run python -m pytest tests/unit/test_basic.py --cov=lib --cov-report=xml --cov-report=term -v`

### Single-test execution (important)

- Single file: `uv run python -m pytest tests/unit/test_basic.py -v`
- Single test function: `uv run python -m pytest tests/unit/test_basic.py::test_true -v`
- By name pattern: `uv run python -m pytest -k "test_true" tests/unit/test_basic.py -v`
- With markers: `uv run python -m pytest -m "unit" -v`
- Excluding slow tests: `uv run python -m pytest -m "not slow" -v`

## 6) Existing Test Configuration

- `abi/abi/pytest.ini` defines:
- `testpaths = tests lib/abi/services src/custom`
- `python_files = *test*.py`
- strict markers/config enabled
- default coverage target is `lib`
- custom markers: `unit`, `integration`, `slow`
- coverage fail threshold currently set to `30`

## 7) Architecture Expectations

- Keep business logic independent from frameworks and external APIs.
- Follow hexagonal architecture principles for Python modules.
- Organize features by domain/module, not by technical layer only.
- In ABI-style modules, common directories are:
- `agents/`, `integrations/`, `ontologies/`, `pipelines/`, `workflows/`, `apps/`.
- Keep module boundaries clear (`src/core`, `src/custom`, `src/marketplace`).
- Prefer adapters/ports patterns when integrating external systems.

## 8) Python Code Style

- Use `ruff format` output as formatting source of truth.
- Follow PEP 8 naming:
- `snake_case` for functions/variables/modules.
- `PascalCase` for classes.
- `UPPER_SNAKE_CASE` for constants.
- Prefer explicit type hints on public functions and complex return values.
- Prefer modern built-in generics (`list[str]`, `dict[str, Any]`) when possible.
- Keep imports grouped: stdlib, third-party, local.
- Avoid wildcard imports.
- Keep functions focused and side effects explicit.
- Do not hide failures; surface actionable errors.
- Catch specific exceptions instead of broad `except:`.
- If logging an exception, preserve traceback or re-raise with context.

## 9) JavaScript / React Style (website)

- Current code uses function components and React hooks.
- Keep component names in `PascalCase` and helper vars in `camelCase`.
- Use single quotes and semicolons to match current files.
- Keep imports at top, grouped by external then local paths.
- Respect Docusaurus alias usage like `@site/...` and `@theme/...`.
- Prefer CSS modules when file already uses `*.module.css`.
- Keep browser-only logic guarded when SSR can occur.
- For API access, keep network concerns in `api/services/*`.

## 10) Naming and File Placement

- Follow existing placement before adding new top-level directories.
- Keep tests near the relevant package area (`tests/`, module-level `_test.py`).
- For ABI modules, mirror existing domain naming patterns.
- Avoid ambiguous filenames like `utils2.py` or `helpers_new.js`.

## 11) Error Handling and Resilience

- Validate required env vars before runtime-critical operations.
- Return clear, user-facing error messages for API failures.
- Add retries/timeouts only where external I/O exists.
- Never swallow exceptions silently.
- For long-running startup logic, emit progress logs with actionable recovery hints.

## 12) Agent Workflow Recommendations

- Before edits, identify which subproject you are touching (`./`, `./abi`, `./abi/abi`).
- Run the narrowest test first (single test/function), then broaden.
- Prefer minimal, focused changes over broad refactors.
- Preserve existing architecture and naming conventions.
- If adding a new adapter/integration, include tests for success and failure paths.
- If a command is heavy (`make`, docker targets), mention expected runtime in status updates.

## 13) Quick Command Cheat Sheet

- Website dev: `npm run start`
- Website build: `npm run build`
- ABI quick API: `cd abi && make api`
- ABI quick chat: `cd abi && make chat`
- ABI full checks: `cd abi/abi && make check`
- ABI full tests: `cd abi/abi && make test`
- ABI single test: `cd abi/abi && uv run python -m pytest tests/unit/test_basic.py::test_true -v`
