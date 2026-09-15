"""Repo-local PubMed publisher. Marketplace origin is recorded in UPSTREAM.md."""

from naas_abi_core import logger
from naas_abi_core.module.Module import (
    BaseModule,
    ModuleConfiguration,
    ModuleDependencies,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService
from naas_abi_core.services.object_storage.ObjectStorageService import (
    ObjectStorageService,
)


class ABIModule(BaseModule):
    dependencies = ModuleDependencies(
        modules=[], services=[ObjectStorageService, DatasetService]
    )

    class Configuration(ModuleConfiguration):
        datastore_path: str = "pubmed"
        ncbi_api_key: str = ""
        ncbi_email: str = ""

    def on_initialized(self):
        super().on_initialized()
        if self.engine.services.dataset_available():
            from pubmed.adapters.secondary.pubmed_dataset_store import (
                PubmedDatasetStore,
            )

            PubmedDatasetStore(self.engine.services.dataset).ensure()

    def api(self, app):
        if not self.engine.services.dataset_available():
            logger.warning("PubMed app requires DatasetService")
            return
        from pubmed.adapters.primary.pubmed_api import router
        from pubmed.pubmed_factory import service

        app.include_router(router(service(self.engine, self._configuration)))
