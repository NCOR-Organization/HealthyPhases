import dagster as dg
from naas_abi_core.orchestrations.DagsterOrchestration import DagsterOrchestration


class IngestionOrchestration(DagsterOrchestration):

    @classmethod
    def New(cls) -> "IngestionOrchestration":
        return cls(
            definitions=dg.Definitions(
                assets=[],
                schedules=[],
                jobs=[],
                sensors=[],
            )
        )