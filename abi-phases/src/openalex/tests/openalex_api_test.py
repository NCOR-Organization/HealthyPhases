from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import dagster as dg
from fastapi import FastAPI
from fastapi.testclient import TestClient
from naas_abi_core.apps.api.abi_api_key_auth import require_abi_api_token
from naas_abi_core.engine.EngineProxy import EngineProxy
from naas_abi_core.module.ModuleOrchestrationLoader import ModuleOrchestrationLoader

from openalex import ABIModule
from openalex.adapters.primary.openalex_api import router
from openalex.application.openalex_service import OpenalexService
from openalex.domain.openalex_errors import EnrichmentNotFound
from openalex.orchestrations.openalex_orchestration import (
    OpenalexOrchestration,
    build_run_requests,
)


def test_api_validates_inputs_requires_auth_and_does_not_call_openalex():
    store, catalog, source = Mock(), Mock(), Mock(api_key="")
    query = str(uuid4())
    catalog.capture.return_value = ({"query": "solitude"}, 1, 2000)
    service = OpenalexService(store, catalog, source)
    app = FastAPI()
    app.include_router(router(service))
    client = TestClient(app)
    assert client.post(
        "/openalex/api/requests", json={"query_id": query}
    ).status_code in (401, 403)
    app.dependency_overrides[require_abi_api_token] = lambda: None
    assert (
        client.post("/openalex/api/requests", json={"query_id": "bad"}).status_code
        == 422
    )
    result = client.post("/openalex/api/requests", json={"query_id": query})
    assert result.status_code == 201 and result.json()["total"] == 2000
    source.lookup.assert_not_called()
    store.rows.return_value = []
    assert client.get("/openalex/api/papers/123").status_code == 404
    assert client.get("/openalex/api/papers/invalid").status_code == 422
    catalog.capture.side_effect = EnrichmentNotFound("absent")
    assert (
        client.post("/openalex/api/requests", json={"query_id": query}).status_code
        == 404
    )


def test_module_configuration_discovery_and_sensor_generations():
    configuration = ABIModule.Configuration(global_config={"ai_mode": "cloud"})
    assert configuration.api_key_secret_name == "OPENALEX_API_KEY"
    assert ModuleOrchestrationLoader.load_orchestrations(ABIModule) == [
        OpenalexOrchestration
    ]
    definitions = OpenalexOrchestration.New().definitions
    dg.Definitions.validate_loadable(definitions)
    row = {"request_id": str(uuid4()), "generation": 2}
    request = build_run_requests([row])[0]
    assert request.run_key.endswith(":2")
    assert request.run_config["ops"]["enrich_papers"]["config"] == row


def test_factory_resolves_optional_secret_without_requiring_credentials(dataset):
    from openalex.openalex_factory import service

    secret = Mock()
    secret.get.return_value = ""
    engine = SimpleNamespace(services=SimpleNamespace(dataset=dataset, secret=secret))
    instance = service(
        EngineProxy(engine, "openalex", ABIModule.dependencies),
        ABIModule.Configuration(global_config={"ai_mode": "cloud"}),
    )
    assert instance.source.api_key == ""
    secret.get.assert_called_once_with("OPENALEX_API_KEY", "")
