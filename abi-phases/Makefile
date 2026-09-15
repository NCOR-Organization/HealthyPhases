.PHONY: install test test-search test-pubmed test-pubmed-network lint build proto
install:
	uv sync

test:
	uv run pytest src/phases_v2 src/pubmed
	node --test src/phases_v2/apps/pipeline/pipeline_test.cjs src/pubmed/apps/search/pubmed_app_test.cjs

test-search:
	uv run pytest src/phases/app
	node --test src/phases/app/tests/reverse_search_test.cjs

lint:
	uv run ruff check src/phases_v2 src/pubmed

build:
	uv build

proto:
	protoc -I src --descriptor_set_in=src/phases_v2/extraction/contracts/extraction_output.pb --include_imports --descriptor_set_out=src/pubmed/contracts/pubmed_publication.pb pubmed/contracts/pubmed_publication.proto
	uv run python src/phases_v2/extraction/contracts/extraction_generate.py
	protoc -I src --descriptor_set_in=src/phases_v2/extraction/contracts/extraction_output.pb --include_imports --descriptor_set_out=src/phases_v2/app/contracts/app_resources.pb phases_v2/app/contracts/app_resources.proto

# Fast publisher and consumer contract checks; live agent/network tests are opt-in.
test-pubmed:
	uv run pytest src/pubmed src/phases_v2/sources
	node --test src/pubmed/apps/search/pubmed_app_test.cjs src/phases_v2/apps/pipeline/pipeline_test.cjs

test-pubmed-network:
	PUBMED_NETWORK_TESTS=1 uv run pytest src/pubmed/tests/pubmed_network_test.py
