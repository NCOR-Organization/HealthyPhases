"""Dataset-backed papers → chunks → extractions pipeline.

This module runs alongside ``phases``; it does not replace it. The two share a
vocabulary but never a named graph, a vector collection, or a dataset.

Datasets are the system of record here. The triple store and the vector
collections are projections built from them and can be dropped and rebuilt
without losing anything.
"""

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
from naas_abi_core.services.triple_store.TripleStoreService import TripleStoreService
from naas_abi_core.services.vector_store.VectorStoreService import VectorStoreService
from pydantic import Field, SecretStr


class PhasesV2Configuration(ModuleConfiguration):
    """Prompts, chunkers and models are declared in code, not configured.

    Configuration example:

        module: phases_v2
        enabled: true
        config:
            papers_root: "phases_v2"
    """

    #: Object-storage prefix the pipeline reads papers from. Every other
    #: module writes into the same storage root, so scanning the root itself
    #: would offer their private data as a source of papers. Owning a prefix
    #: keeps them out of scope by construction rather than by a blacklist that
    #: needs updating whenever a module is added.
    papers_root: str = "phases_v2"
    openai_api_key: SecretStr | None = None
    extraction_workers: int = Field(default=20, ge=1, strict=True)


class ABIModule(BaseModule[PhasesV2Configuration]):
    Configuration = PhasesV2Configuration
    dependencies: ModuleDependencies = ModuleDependencies(
        modules=[],
        services=[
            ObjectStorageService,
            DatasetService,
            TripleStoreService,
            VectorStoreService,
        ],
    )

    def api(self, app) -> None:
        """Mount the pipeline and reverse-search apps' endpoints.

        Each is wrapped on its own: a wiring error in one must not stop the
        other from mounting, or the engine from booting — the way v1's `api()`
        also degrades rather than taking the API down.
        """
        try:
            from phases_v2.app.adapters.primary.PipelineAPI import register
            from phases_v2.app.factory import app_service

            register(
                app,
                app_service(
                    self._engine, papers_root=self._configuration.papers_root
                ),
            )
            logger.debug("Mounted phases_v2 pipeline API at /phases_v2/api")
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to mount the phases_v2 pipeline app: {exc}")

        try:
            from phases_v2.app.adapters.primary.SearchAPI import (
                register as register_search,
            )
            from phases_v2.search.factory import search_service

            register_search(
                app, search_service(self._engine, configuration=self._configuration)
            )
            logger.debug("Mounted phases_v2 reverse-search API at /phases_v2/api/search")
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to mount the phases_v2 reverse-search app: {exc}")

    def on_initialized(self):
        """Create the datasets and publish what this module declares."""
        super().on_initialized()
        load_module_declarations(self._engine)


def ensure_datasets_if_available(engine) -> set[str]:
    """Create the pipeline's datasets, if this deployment has a dataset service.

    Runs in every process that starts the engine — API, Dagster daemon, each
    run worker — so it must be cheap and safe to repeat. A deployment with no
    dataset service still boots: the module says so and stays inert rather than
    taking the engine down with it.

    Kept separate from ``on_initialized`` so the decision can be tested without
    standing up the module lifecycle around it.
    """
    if not engine.services.dataset_available():
        logger.warning(
            "phases_v2: no dataset service is configured, so the pipeline's "
            "datasets were not created. The module is loaded but inert."
        )
        return set()

    from phases_v2.datasets.store import ensure_datasets

    created = ensure_datasets(engine.services.dataset)
    if created:
        logger.info(f"phases_v2: created datasets {', '.join(sorted(created))}")
    return created


def register_declarations(store) -> dict[str, list[str]]:
    """Publish the prompts, chunkers and models this module declares.

    Every write is an upsert, so this needs no read: re-registering an
    unchanged declaration rewrites the row it already had. That is what makes
    it safe to run on every engine start in every process.
    """
    from phases_v2.chunking.chunkers import DECLARED_CHUNKERS
    from phases_v2.chunking.registry import register_chunkers
    from phases_v2.models.catalog import DECLARED_MODELS, register_models
    from phases_v2.prompts.domain import register_prompts
    from phases_v2.prompts.templates import declared_prompts

    return {
        "prompts": register_prompts(store, list(declared_prompts())),
        "chunkers": register_chunkers(store, list(DECLARED_CHUNKERS)),
        "models": register_models(store, list(DECLARED_MODELS)),
    }


def load_module_declarations(engine) -> dict[str, list[str]]:
    """Ensure the datasets exist, then publish everything declared in code.

    Returns the ids published per registry, or an empty mapping when this
    deployment has no dataset service to publish to.
    """
    ensure_datasets_if_available(engine)
    if not engine.services.dataset_available():
        return {}

    from phases_v2.datasets.row_store import DatasetRowStore

    return register_declarations(DatasetRowStore(engine.services.dataset))
