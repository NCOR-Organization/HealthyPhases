"""Shared embedding configuration for ingestion and reverse search."""

from __future__ import annotations

from phases_v2 import PhasesV2Configuration
from phases_v2.projection.adapters.secondary.OpenAIEmbedder import OpenAIEmbedder


def embedder_for(
    engine, *, configuration: PhasesV2Configuration | None = None
) -> OpenAIEmbedder:
    # API callers pass their own configuration: the module's engine proxy
    # intentionally cannot look up the calling module in engine.modules.
    if configuration is None:
        configuration = engine.modules["phases_v2"].configuration
    secret = configuration.openai_api_key
    return OpenAIEmbedder(api_key=secret.get_secret_value() if secret else None)
