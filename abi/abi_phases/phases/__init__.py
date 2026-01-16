from naas_abi_core.module.Module import BaseModule, ModuleConfiguration, ModuleDependencies
from naas_abi_core.services.object_storage.ObjectStorageService import ObjectStorageService
from naas_abi_core.services.vector_store.VectorStoreService import VectorStoreService
import os
from naas_abi_core.services.triple_store.TripleStoreService import TripleStoreService

class PhasesConfiguration(ModuleConfiguration):
    google_api_key: str

class ABIModule(BaseModule[PhasesConfiguration]):
    Configuration = PhasesConfiguration
    dependencies: ModuleDependencies = ModuleDependencies(
        modules=["naas_abi_marketplace.applications.pubmed", "naas_abi_marketplace.ai.chatgpt"],
        services=[ObjectStorageService, VectorStoreService, TripleStoreService],
    )
    
    
    def on_initialized(self):
        from naas_abi_core.utils.onto2py import onto2py
        
        python_code = onto2py(os.path.join(os.path.dirname(__file__), "ontologies", "documents.ttl"))
        with open(os.path.join(os.path.dirname(__file__), "ontologies", "documents.py"), "w") as f:
            f.write(python_code)
        
        