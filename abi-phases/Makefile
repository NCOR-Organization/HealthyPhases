.PHONY: install test test-search lint build proto
install:
	uv sync

test:
	uv run pytest src/phases_v2
	node --test src/phases_v2/apps/pipeline/pipeline_test.cjs

test-search:
	uv run pytest src/phases/app
	node --test src/phases/app/tests/reverse_search_test.cjs

lint:
	uvx ruff check src/phases_v2

build:
	uv build

proto:
	uv run python src/phases_v2/extraction/contracts/extraction_generate.py
	protoc -I src --descriptor_set_in=src/phases_v2/extraction/contracts/extraction_output.pb --include_imports --descriptor_set_out=src/phases_v2/app/contracts/app_resources.pb phases_v2/app/contracts/app_resources.proto
