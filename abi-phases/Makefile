.PHONY: install test test-search test-pubmed test-pubmed-network lint build proto
install:
	uv sync

.PHONY: test-review
test-review:
	uv run pytest src/phases_v2/review src/phases_v2/projection/probabilistic_test.py src/phases_v2/orchestrations/PhasesV2Orchestration_test.py
	node --test src/phases_v2/apps/reverse_search/tests/reverse_search_test.cjs

test:
	uv run pytest src/phases_v2 src/pubmed src/openalex
	node --test src/phases_v2/apps/pipeline/pipeline_test.cjs src/pubmed/apps/search/pubmed_app_test.cjs src/openalex/apps/openalex/openalex_app_test.cjs

test-search:
	uv run --with pytest pytest src/phases_v2/search src/phases_v2/app/adapters/primary/SearchAPI_test.py src/phases_v2/extraction/domain_test.py src/phases_v2/projection/probabilistic_test.py src/phases_v2/datasets/schemas_test.py src/phases_v2/orchestrations/PhasesV2Orchestration_test.py src/phases_v2/README_test.py
	node --test src/phases_v2/apps/reverse_search/tests/reverse_search_test.cjs

lint:
	uv run ruff check src/phases_v2 src/pubmed src/openalex

build:
	uv build

proto:
	protoc -I src --descriptor_set_in=src/phases_v2/extraction/contracts/extraction_output.pb --include_imports --descriptor_set_out=src/phases_v2/review/contracts/review.pb phases_v2/review/contracts/review.proto
	protoc -I src --descriptor_set_in=src/phases_v2/extraction/contracts/extraction_output.pb --include_imports --descriptor_set_out=src/openalex/contracts/openalex_enrichment.pb openalex/contracts/openalex_enrichment.proto
	protoc -I src --descriptor_set_in=src/phases_v2/extraction/contracts/extraction_output.pb --include_imports --descriptor_set_out=src/pubmed/contracts/pubmed_publication.pb pubmed/contracts/pubmed_publication.proto
	uv run python src/phases_v2/extraction/contracts/extraction_generate.py
	protoc -I src --descriptor_set_in=src/phases_v2/extraction/contracts/extraction_output.pb --include_imports --descriptor_set_out=src/phases_v2/app/contracts/app_resources.pb phases_v2/app/contracts/app_resources.proto

# Fast publisher and consumer contract checks; live agent/network tests are opt-in.
test-pubmed:
	uv run pytest src/pubmed src/phases_v2/sources
	node --test src/pubmed/apps/search/pubmed_app_test.cjs src/phases_v2/apps/pipeline/pipeline_test.cjs

test-pubmed-network:
	PUBMED_NETWORK_TESTS=1 uv run pytest src/pubmed/tests/pubmed_network_test.py

.PHONY: test-openalex
test-openalex:
	uv run pytest src/openalex src/pubmed/tests/pubmed_library_test.py
	node --test src/openalex/apps/openalex/openalex_app_test.cjs src/pubmed/apps/search/pubmed_app_test.cjs
