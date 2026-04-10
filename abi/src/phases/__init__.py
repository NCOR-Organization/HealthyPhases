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
            "relations.ttl": "relations.py",
        }

        # for ttl_name, py_name in ttl_to_py.items():
        #     ttl_path = os.path.join(ontologies_dir, ttl_name)
        #     if not os.path.exists(ttl_path):
        #         continue

        #     python_code = onto2py(ttl_path)
        #     py_file_path = os.path.join(ontologies_dir, py_name)
        #     existing_code = None
        #     if os.path.exists(py_file_path):
        #         with open(py_file_path, "r") as f:
        #             existing_code = f.read()
            
        #     import hashlib

        #     def compute_hash(s: str) -> str:
        #         return hashlib.sha256(s.encode("utf-8")).hexdigest()

        #     code_hash = compute_hash(python_code)
        #     existing_hash = compute_hash(existing_code) if existing_code is not None else None
            
        #     if code_hash != existing_hash:
        #         print(f"Writing {py_file_path} as we have newer code")
        #         with open(py_file_path, "w") as f:
        #             f.write(python_code)
