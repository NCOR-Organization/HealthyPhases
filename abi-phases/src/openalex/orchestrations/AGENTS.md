# OpenAlex orchestration

Use `OpenalexOrchestration.New()` to expose Dagster definitions. The sensor submits one oldest pending request generation at a time. Each worker handles one batch and advances the generation. Failure and cancellation handlers must ignore stale generations. Keep use cases in the application service and test definitions/discovery alongside the module tests.
