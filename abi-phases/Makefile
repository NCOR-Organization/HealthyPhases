.PHONY: install test lint build proto
install:
	uv sync

test:
	uv run pytest src/phases_v2

lint:
	uvx ruff check src/phases_v2

build:
	uv build

proto:
	uv run python src/phases_v2/extraction/contracts/extraction_generate.py
