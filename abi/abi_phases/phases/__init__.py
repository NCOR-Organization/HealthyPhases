from naas_abi_core.module.Module import (
    BaseModule,
    ModuleConfiguration,
    ModuleDependencies,
)
from naas_abi_core.services.object_storage.ObjectStorageService import (
    ObjectStorageService,
)
from naas_abi_core.services.vector_store.VectorStoreService import VectorStoreService
import os
from naas_abi_core.services.triple_store.TripleStoreService import TripleStoreService


class PhasesConfiguration(ModuleConfiguration):
    google_api_key: str


class ABIModule(BaseModule[PhasesConfiguration]):
    Configuration = PhasesConfiguration
    dependencies: ModuleDependencies = ModuleDependencies(
        modules=[
            "naas_abi_marketplace.applications.pubmed",
            "naas_abi_marketplace.ai.chatgpt",
        ],
        services=[ObjectStorageService, VectorStoreService, TripleStoreService],
    )

    def on_initialized(self):
        from naas_abi_core.utils.onto2py import onto2py

        ontologies_dir = os.path.join(os.path.dirname(__file__), "ontologies")
        ttl_to_py = {
            "documents.ttl": "documents.py",
            "axioms.ttl": "axioms.py",
            "labels.ttl": "labels.py",
        }

        for ttl_name, py_name in ttl_to_py.items():
            ttl_path = os.path.join(ontologies_dir, ttl_name)
            if not os.path.exists(ttl_path):
                continue

            python_code = onto2py(ttl_path)
            with open(os.path.join(ontologies_dir, py_name), "w") as f:
                f.write(python_code)
