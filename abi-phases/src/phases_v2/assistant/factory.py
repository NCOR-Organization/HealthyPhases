"""Wiring for the assistant: the same services the app's endpoints are built from."""

from __future__ import annotations

from naas_abi_core import logger

from phases_v2.assistant.confirmations import ConfirmationGuard
from phases_v2.assistant.request_context import nexus_context
from phases_v2.assistant.workspace import WorkspaceActions

#: One per process, so every copy of the agent honours the same tokens.
GUARD = ConfirmationGuard()


def workspace_actions(engine, configuration) -> WorkspaceActions:
    """The actions, with every service built on first use rather than here.

    The agent is built when Nexus starts, alongside every other agent, and a
    failure there stops them all loading; a service that cannot be built yet
    only makes the tools that need it answer that it is unavailable.
    """
    from phases_v2.app.factory import app_service
    from phases_v2.search.factory import search_service

    return WorkspaceActions(
        lambda: app_service(engine, papers_root=configuration.papers_root),
        guard=GUARD,
        context=nexus_context,
        search=lambda: search_service(engine, configuration=configuration),
        pubmed=_pubmed,
        openalex=_openalex,
    )


# Each module's engine reaches only the services that module declares, so the
# PubMed and OpenAlex services are built from their own module's engine.


def _pubmed():
    from pubmed import ABIModule

    try:
        module = ABIModule.get_instance()
    except ValueError:
        logger.info("phases_v2 assistant: the pubmed module is not loaded")
        return None
    from pubmed.pubmed_factory import service

    return service(module.engine, module.configuration)


def _openalex():
    from openalex import ABIModule

    try:
        module = ABIModule.get_instance()
    except ValueError:
        logger.info("phases_v2 assistant: the openalex module is not loaded")
        return None
    from openalex.openalex_factory import service

    return service(module.engine, module.configuration)
