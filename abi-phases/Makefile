.PHONY: install test test-app test-search test-pubmed test-pubmed-network lint build proto
install:
	uv sync

APP_TESTS = src/phases_v2/apps/workspace/tests

test:
	uv run pytest tests src/phases_v2 src/pubmed src/openalex
	node --test $(APP_TESTS)/*_test.cjs

# The HealthyPhases workspace app on its own: manifest/packaging checks and browser logic.
test-app:
	uv run pytest src/phases_v2/apps/workspace
	node --test $(APP_TESTS)/*_test.cjs

test-search:
	uv run --with pytest pytest src/phases_v2/search src/phases_v2/app/adapters/primary/SearchAPI_test.py src/phases_v2/extraction/domain_test.py src/phases_v2/projection/probabilistic_test.py src/phases_v2/datasets/schemas_test.py src/phases_v2/orchestrations/PhasesV2Orchestration_test.py src/phases_v2/README_test.py
	node --test $(APP_TESTS)/search_test.cjs

lint:
	uv run ruff check tests src/phases_v2 src/pubmed src/openalex

build:
	uv build

proto:
	protoc -I src --descriptor_set_in=src/phases_v2/extraction/contracts/extraction_output.pb --include_imports --descriptor_set_out=src/openalex/contracts/openalex_enrichment.pb openalex/contracts/openalex_enrichment.proto
	protoc -I src --descriptor_set_in=src/phases_v2/extraction/contracts/extraction_output.pb --include_imports --descriptor_set_out=src/pubmed/contracts/pubmed_publication.pb pubmed/contracts/pubmed_publication.proto
	uv run python src/phases_v2/extraction/contracts/extraction_generate.py
	protoc -I src --descriptor_set_in=src/phases_v2/extraction/contracts/extraction_output.pb --include_imports --descriptor_set_out=src/phases_v2/app/contracts/app_resources.pb phases_v2/app/contracts/app_resources.proto

# Fast publisher and consumer contract checks; live agent/network tests are opt-in.
test-pubmed:
	uv run pytest src/pubmed src/phases_v2/sources
	node --test $(APP_TESTS)/library_test.cjs $(APP_TESTS)/runs_test.cjs

test-pubmed-network:
	PUBMED_NETWORK_TESTS=1 uv run pytest src/pubmed/tests/pubmed_network_test.py

.PHONY: test-openalex
test-openalex:
	uv run pytest src/openalex src/pubmed/tests/pubmed_library_test.py
	node --test $(APP_TESTS)/library_test.cjs
