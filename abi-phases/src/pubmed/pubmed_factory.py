"""Composition root shared by module API, agent and background workers."""

from pubmed.adapters.secondary.pubmed_dataset_store import PubmedDatasetStore
from pubmed.adapters.secondary.pubmed_ncbi import NcbiSource
from pubmed.adapters.secondary.pubmed_object_storage import PubmedObjectStorage
from pubmed.application.pubmed_service import PubmedService


def service(engine, configuration):
    store = PubmedDatasetStore(engine.services.dataset)
    store.ensure()
    return PubmedService(
        store,
        NcbiSource(api_key=configuration.ncbi_api_key, email=configuration.ncbi_email),
        PubmedObjectStorage(engine.services.object_storage),
        configuration.datastore_path,
    )
