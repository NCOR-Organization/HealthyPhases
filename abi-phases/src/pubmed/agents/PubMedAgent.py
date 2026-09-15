from __future__ import annotations

from langchain_core.tools import tool
from naas_abi_core.services.agent.Agent import (
    Agent,
    AgentConfiguration,
    AgentSharedState,
)


class PubMedAgent(Agent):
    name: str = "PubMedAgent"
    description: str = "PubMedAgent is an agent that can search for papers in PubMed."
    system_prompt: str = """You are a PubMed Agent aimed to help users search for papers in PubMed.
When using tools, you might receive a Turtle serialized graph as a response.
You must always display the request results as a Markdown table.
"""

    @classmethod
    def New(
        cls,
        agent_shared_state: AgentSharedState | None = None,
        agent_configuration: AgentConfiguration | None = None,
    ) -> PubMedAgent:
        from pubmed import ABIModule
        from pubmed.pubmed_factory import service

        module = ABIModule.get_instance()
        registry = module.engine.services.model_registry
        assert registry is not None, "ModelRegistryService not initialized"
        chat_model = registry.get_default_chat_model()
        publisher = service(module.engine, module._configuration)

        @tool(
            description="Search PubMed and save a query for later ingestion. Returns its query_id and papers."
        )
        def search_papers(query: str, max_results: int = 100) -> dict:
            return publisher.search({"query": query, "max_results": max_results})

        @tool(
            description="Queue ingestion of a saved query. Downloads run asynchronously and publish a dataset."
        )
        def request_ingestion(query_id: str) -> dict:
            return publisher.submit({"query_id": query_id})

        @tool(
            description="Check the status and per-paper outcomes of a PubMed ingestion request."
        )
        def request_status(request_id: str) -> dict:
            return publisher.one("run_requests", request_id=request_id)

        tools = [search_papers, request_ingestion, request_status]

        if agent_configuration is None:
            agent_configuration = AgentConfiguration(system_prompt=cls.system_prompt)
        if agent_shared_state is None:
            agent_shared_state = AgentSharedState(
                thread_id=str(__import__("uuid").uuid4().hex)
            )

        return cls(
            name=cls.name,
            description=cls.description,
            chat_model=chat_model,
            tools=tools,
            agents=[],
            state=agent_shared_state,
            configuration=agent_configuration,
            memory=None,
        )
