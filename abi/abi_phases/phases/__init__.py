from naas_abi_core.module.Module import BaseModule, ModuleConfiguration, ModuleDependencies


class PhasesConfiguration(ModuleConfiguration):
    google_api_key: str

class ABIModule(BaseModule[PhasesConfiguration]):
    Configuration = PhasesConfiguration
    dependencies: ModuleDependencies = ModuleDependencies(
        modules=["naas_abi_marketplace.applications.pubmed"],
        services=[],
    )