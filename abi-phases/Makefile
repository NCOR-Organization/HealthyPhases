.PHONY: install test test-search lint build proto
install:
	uv sync

test:
	uv run pytest src/phases_v2
	node --test src/phases_v2/apps/pipeline/pipeline_test.cjs

test-search:
	uv run --with pytest pytest src/phases_v2/search src/phases_v2/app/adapters/primary/SearchAPI_test.py src/phases_v2/extraction/domain_test.py src/phases_v2/projection/probabilistic_test.py src/phases_v2/datasets/schemas_test.py src/phases_v2/orchestrations/PhasesV2Orchestration_test.py src/phases_v2/README_test.py
	node --test src/phases_v2/apps/reverse_search/tests/reverse_search_test.cjs

lint:
	uvx ruff check src/phases_v2

build:
	uv build

proto:
	uv run python src/phases_v2/extraction/contracts/extraction_generate.py
	protoc -I src --descriptor_set_in=src/phases_v2/extraction/contracts/extraction_output.pb --include_imports --descriptor_set_out=src/phases_v2/app/contracts/app_resources.pb phases_v2/app/contracts/app_resources.proto
