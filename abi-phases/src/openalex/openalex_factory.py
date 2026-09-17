"""Composition root for HTTP and Dagster entry points."""

from openalex.adapters.secondary.openalex_dataset_store import OpenalexDatasetStore
from openalex.adapters.secondary.openalex_pubmed_catalog import PubmedCatalog
from openalex.adapters.secondary.openalex_source import OpenalexSource
from openalex.application.openalex_service import OpenalexService


def service(engine, configuration):
    store = OpenalexDatasetStore(engine.services.dataset)
    store.ensure()
    source = OpenalexSource(
        api_key=engine.services.secret.get(configuration.api_key_secret_name, ""),
        interval=configuration.request_interval_seconds,
    )
    return OpenalexService(
        store,
        PubmedCatalog(engine.services.dataset),
        source,
        batch_size=configuration.batch_size,
        request_budget=configuration.request_budget,
        cache_days=configuration.cache_days,
    )
