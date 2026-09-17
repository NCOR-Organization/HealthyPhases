"""OpenAlex enrichment module; no model provider or PubMed module dependency."""

from naas_abi_core.module.Module import (
    BaseModule,
    ModuleConfiguration,
    ModuleDependencies,
)
from naas_abi_core.services.dataset.DatasetService import DatasetService
from naas_abi_core.services.secret.Secret import Secret
from pydantic import Field


class ABIModule(BaseModule):
    dependencies = ModuleDependencies(modules=[], services=[DatasetService, Secret])

    class Configuration(ModuleConfiguration):
        api_key_secret_name: str = "OPENALEX_API_KEY"
        batch_size: int = Field(default=25, ge=1, le=100)
        request_budget: int = Field(default=10000, ge=2, le=1000000)
        cache_days: int = Field(default=7, ge=0, le=365)
        request_interval_seconds: float = Field(default=1.0, ge=0.1, le=60)

    def on_initialized(self):
        super().on_initialized()
        if self.engine.services.dataset_available():
            from openalex.adapters.secondary.openalex_dataset_store import (
                OpenalexDatasetStore,
            )

            OpenalexDatasetStore(self.engine.services.dataset).ensure()

    def api(self, app):
        if self.engine.services.dataset_available():
            from openalex.adapters.primary.openalex_api import router
            from openalex.openalex_factory import service

            app.include_router(router(service(self.engine, self._configuration)))
