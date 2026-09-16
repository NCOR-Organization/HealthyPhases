"""Module credentials reach the real LangChain client without process env."""

from types import SimpleNamespace

import pytest

from phases_v2 import PhasesV2Configuration
from phases_v2.projection.embedding_factory import embedder_for


@pytest.mark.parametrize("explicit_configuration", [True, False])
def test_module_credentials_configure_embedding_client(
    monkeypatch, explicit_configuration
):
    import openai.resources.embeddings

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = PhasesV2Configuration(
        global_config={"ai_mode": "cloud"}, openai_api_key="module-test-key"
    )
    engine = SimpleNamespace(
        modules={"phases_v2": SimpleNamespace(configuration=config)}
    )
    calls = []

    def create(self, *, input, **kwargs):
        calls.append((self._client.api_key, kwargs["model"], kwargs["dimensions"]))
        return {"data": [{"embedding": [1.0, 0.0]} for _ in input]}

    monkeypatch.setattr(openai.resources.embeddings.Embeddings, "create", create)
    embedder = embedder_for(
        engine, configuration=config if explicit_configuration else None
    )
    assert embedder.embed(["solitude"]) == [[1.0, 0.0]]
    assert calls == [("module-test-key", "text-embedding-3-large", 3072)]
    assert "module-test-key" not in repr(config)
