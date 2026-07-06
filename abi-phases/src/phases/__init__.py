import hashlib
import os

from fastapi import FastAPI
from naas_abi_core import logger
from naas_abi_core.module.Module import (
    BaseModule,
    ModuleConfiguration,
    ModuleDependencies,
)
from naas_abi_core.services.object_storage.ObjectStorageService import (
    ObjectStorageService,
)
from naas_abi_core.services.triple_store.TripleStoreService import TripleStoreService
from naas_abi_core.services.vector_store.VectorStoreService import VectorStoreService


class PhasesConfiguration(ModuleConfiguration):
    google_api_key: str


# bfo_core must come first: documents.ttl owl:imports it, so its generated .py
# must exist before documents.py is regenerated and imported.
_ONTOLOGY_TTL_TO_PY: list[tuple[str, str]] = [
    ("bfo_core.ttl", "bfo_core.py"),
    ("documents.ttl", "documents.py"),
    ("axioms.ttl", "axioms.py"),
    ("labels.ttl", "labels.py"),
    ("relations.ttl", "relations.py"),
]


class ABIModule(BaseModule[PhasesConfiguration]):
    Configuration = PhasesConfiguration
    dependencies: ModuleDependencies = ModuleDependencies(
        modules=[
            "naas_abi_marketplace.applications.pubmed",
            "naas_abi_marketplace.ai.chatgpt",
        ],
        services=[ObjectStorageService, VectorStoreService, TripleStoreService],
    )

    def on_load(self):
        # Regenerate before super().on_load() — it triggers orchestration loading,
        # which imports phases.ontologies.documents whose source is rewritten here.
        self._regenerate_ontologies()
        super().on_load()

    def api(self, app: FastAPI) -> None:
        """Mount the reverse-search API + static UI onto the ABI FastAPI app.

        Endpoints live under ``/phases/api`` and the single-page UI is served at
        ``/phases/app``. The search domain is wired from this module's engine
        services so it resolves against whatever triple/vector store backs the
        running deployment.
        """
        try:
            from phases.app.adapters.primary.SearchAPI import register
            from phases.app.factory import SearchServiceFactory

            service = SearchServiceFactory.from_engine(self.engine)
            register(app, service)
            logger.debug("Mounted phases reverse-search API at /phases/api")
        except Exception as exc:  # never let an app wiring error break API boot
            logger.error(f"Failed to mount phases reverse-search app: {exc}")

    def _regenerate_ontologies(self) -> None:
        # Skip the import + onto2py call entirely when nothing changed —
        # otherwise non-deterministic generator output (dict ordering, etc.)
        # rewrites the .py files on every load and trips the container's
        # file watcher into a needless refresh.
        #
        # An explicit opt-out is also honored: PHASES_SKIP_ONTOLOGY_REGEN=1
        # lets container images use only the .py files that were generated
        # and committed at build time.
        if os.environ.get("PHASES_SKIP_ONTOLOGY_REGEN", "").lower() in {"1", "true", "yes"}:
            return

        ontologies_dir = os.path.join(os.path.dirname(__file__), "ontologies")

        for ttl_name, py_name in _ONTOLOGY_TTL_TO_PY:
            ttl_path = os.path.join(ontologies_dir, ttl_name)
            if not os.path.exists(ttl_path):
                continue

            py_file_path = os.path.join(ontologies_dir, py_name)
            hash_sidecar_path = py_file_path + ".ttlhash"

            with open(ttl_path, "rb") as f:
                ttl_hash = hashlib.sha256(f.read()).hexdigest()

            # Fast path 1: TTL hash matches the sidecar recorded at the last
            # successful generation → nothing to do, don't even invoke onto2py.
            if os.path.exists(py_file_path) and os.path.exists(hash_sidecar_path):
                with open(hash_sidecar_path, "r") as f:
                    recorded_hash = f.read().strip()
                if recorded_hash == ttl_hash:
                    continue

            # Fast path 2: no sidecar yet, but a generated .py exists that is
            # at least as new as the .ttl. Assume it's still valid (typical in
            # a freshly built container image where we just want to write the
            # sidecar without re-running onto2py).
            if (
                os.path.exists(py_file_path)
                and not os.path.exists(hash_sidecar_path)
                and os.path.getmtime(py_file_path) >= os.path.getmtime(ttl_path)
            ):
                try:
                    with open(hash_sidecar_path, "w") as f:
                        f.write(ttl_hash)
                except OSError as e:
                    print(f"Warning: could not write {hash_sidecar_path}: {e}")
                continue

            # Slow path: actually regenerate. Wrap in try/except so an
            # environment where onto2py can't resolve imports (e.g. paths
            # outside any naas_abi* package) doesn't bring down module load —
            # the committed .py file is still usable.
            try:
                from naas_abi_core.utils.onto2py import onto2py

                python_code = onto2py(ttl_path)
            except Exception as e:
                print(
                    f"Warning: skipping ontology regeneration for {ttl_name}: {e}. "
                    f"Falling back to the existing {py_name}."
                )
                continue

            existing_code = None
            if os.path.exists(py_file_path):
                with open(py_file_path, "r") as f:
                    existing_code = f.read()

            new_hash = hashlib.sha256(python_code.encode("utf-8")).hexdigest()
            old_hash = (
                hashlib.sha256(existing_code.encode("utf-8")).hexdigest()
                if existing_code is not None
                else None
            )
            if new_hash != old_hash:
                print(f"Writing {py_file_path} as we have newer code")
                with open(py_file_path, "w") as f:
                    f.write(python_code)

            # Record the TTL hash so subsequent loads short-circuit regardless
            # of whether the generated .py changed.
            try:
                with open(hash_sidecar_path, "w") as f:
                    f.write(ttl_hash)
            except OSError as e:
                print(f"Warning: could not write {hash_sidecar_path}: {e}")
