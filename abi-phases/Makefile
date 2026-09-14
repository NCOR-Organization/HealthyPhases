.PHONY: install test test-search lint build proto
install:
	uv sync

test:
	uv run pytest src/phases_v2

test-search:
	uv run --with pytest pytest src/phases_v2/search src/phases_v2/app/adapters/primary/SearchAPI_test.py src/phases_v2/extraction/domain_test.py src/phases_v2/projection/probabilistic_test.py src/phases_v2/datasets/schemas_test.py src/phases_v2/orchestrations/PhasesV2Orchestration_test.py src/phases_v2/README_test.py
	node --test src/phases_v2/apps/reverse_search/tests/reverse_search_test.cjs

lint:
	uvx ruff check src/phases_v2

build:
	uv build

proto:
	uv run python src/phases_v2/extraction/contracts/extraction_generate.py
