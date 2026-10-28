"""The assistant Nexus loads in its right pane while the HealthyPhases app is open.

Covers how the pane finds it (the app manifest's agent ref, resolved the way
Nexus resolves it, and the workspace's agent list), how it is built, what its
instructions say, and a whole conversation through the agent's own graph: a
costly action asked for and confirmed, with a scripted chat model in place of
a real one.
"""

import json
import pathlib
from types import SimpleNamespace

import pytest
import yaml
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import MemorySaver
from naas_abi.apps.nexus.apps.api.app.core.workspace_catalog_seed import (
    resolve_agent_ref,
)
from naas_abi_core.module.ModuleAgentLoader import ModuleAgentLoader
from naas_abi_core.services.agent.Agent import AgentConfiguration, AgentSharedState
from naas_abi_core.services.agent.context import agent_chat_id, agent_user_email

import phases_v2
import pubmed
from phases_v2.agents.WorkspaceAssistantAgent import (
    INSTRUCTIONS,
    WorkspaceAssistantAgent,
)
from phases_v2.assistant import factory
from phases_v2.assistant.request_context import (
    nexus_context,
    turn_marker,
    turn_markers,
)
from phases_v2.assistant.tools import build_tools
from phases_v2.assistant.workspace import Unavailable
from phases_v2.assistant.workspace_test import (
    CLAIMS,
    PAPER,
    build_env,
    build_store,
    run_choices,
)

SRC = pathlib.Path(phases_v2.__file__).parents[1]
PROJECT = SRC.parent
MANIFEST = SRC / "phases_v2" / "apps" / "workspace" / "manifest.json"
REF = "phases_v2 WorkspaceAssistantAgent"
SECTIONS = (
    "Overview",
    "Library",
    "Collections",
    "Prompts",
    "Runs",
    "Results",
    "Search",
)


class ScriptedChat(GenericFakeChatModel):
    """Answers each turn with whatever ``script`` makes of the conversation."""

    script: object = None

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.script(messages))])

    def bind_tools(self, tools, **kwargs):
        return self


def chat(script):
    return ScriptedChat(messages=iter([]), script=script)


# -- how the pane finds it ---------------------------------------------------------


def _registry():
    """Agent classes keyed the way Nexus keys them (agents adapter)."""
    return {
        f"{cls.__module__}/{cls.__name__}": cls
        for module in (phases_v2.ABIModule, pubmed.ABIModule)
        for cls in ModuleAgentLoader.load_agents(module)
    }


def test_the_app_manifest_binds_the_pane_to_the_registered_assistant():
    manifest = json.loads(MANIFEST.read_text())

    assert manifest["agent"] == REF
    key = resolve_agent_ref(manifest["agent"], _registry())
    assert _registry()[key] is WorkspaceAssistantAgent


def test_the_module_registers_only_the_assistant():
    assert ModuleAgentLoader.load_agents(phases_v2.ABIModule) == [
        WorkspaceAssistantAgent
    ]


@pytest.mark.parametrize("config", ["config.yaml", "config.local.yaml"])
def test_the_workspace_runs_the_assistant_for_owners_and_members(config):
    """Nexus enables only the agents a workspace lists, whoever opens the pane."""
    loaded = yaml.safe_load((PROJECT / config).read_text())
    nexus = next(m for m in loaded["modules"] if m["module"] == "naas_abi")["config"][
        "nexus_config"
    ]
    [organization] = nexus["organizations"]
    [workspace] = organization["workspaces"]

    assert REF in workspace["agents"]
    assert resolve_agent_ref(REF, _registry())
    roles = nexus["feature_flags"]["role_baseline"]
    for role in ("owner", "member"):
        assert {"chat", "apps"} <= set(roles[role]), role


@pytest.mark.parametrize("config", ["config.yaml", "config.local.yaml"])
def test_the_workspace_turns_the_healthyphases_app_on(config):
    """Without a saved toggle, Nexus shows only the apps the workspace seed lists."""
    loaded = yaml.safe_load((PROJECT / config).read_text())
    nexus = next(m for m in loaded["modules"] if m["module"] == "naas_abi")["config"][
        "nexus_config"
    ]
    [organization] = nexus["organizations"]
    [workspace] = organization["workspaces"]

    # Nexus names a module's app "<module>:<app folder>".
    assert (PROJECT / "src/phases_v2/apps/workspace/manifest.json").is_file()
    assert "phases_v2:workspace" in workspace["apps"]


# -- how it is built -------------------------------------------------------------


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    return build_store(tmp_path_factory.mktemp("assistant-agent"))


def test_new_builds_the_assistant_with_the_default_chat_model_and_its_tools(
    store, monkeypatch
):
    env = build_env(store)
    model = chat(lambda messages: AIMessage("Hello"))
    module = SimpleNamespace(
        engine=SimpleNamespace(
            services=SimpleNamespace(
                model_registry=SimpleNamespace(get_default_chat_model=lambda: model)
            )
        ),
        configuration=SimpleNamespace(papers_root="phases_v2"),
    )
    monkeypatch.setattr(phases_v2.ABIModule, "get_instance", lambda: module)
    monkeypatch.setattr(
        factory, "workspace_actions", lambda engine, configuration: env.actions
    )

    agent = WorkspaceAssistantAgent.New()

    assert agent.name == "HealthyPhases Assistant"
    assert agent._chat_model is model
    assert {t.name for t in agent.tools} == {t.name for t in build_tools(env.actions)}
    assert agent.configuration.system_prompt == INSTRUCTIONS


def test_the_factory_wires_the_apps_services_and_skips_modules_not_loaded(
    store, monkeypatch
):
    import openalex

    def not_loaded():
        raise ValueError("Module not initialized")

    monkeypatch.setattr(pubmed.ABIModule, "get_instance", not_loaded)
    monkeypatch.setattr(openalex.ABIModule, "get_instance", not_loaded)
    engine = SimpleNamespace(
        services=SimpleNamespace(dataset=store.dataset, object_storage=store.storage)
    )

    actions = factory.workspace_actions(
        engine, SimpleNamespace(papers_root="phases_v2")
    )

    assert actions._guard is factory.GUARD
    assert {c["chunker_id"] for c in actions.list_models_and_chunkers()["chunkers"]}
    with pytest.raises(Unavailable, match="PubMed is unavailable in this deployment"):
        actions.search_pubmed("solitude")
    assert actions.list_downloads_and_enrichments()["unavailable"] == [
        "PubMed is unavailable in this deployment.",
        "OpenAlex enrichment is unavailable in this deployment.",
    ]

    monkeypatch.setattr(
        pubmed.ABIModule,
        "get_instance",
        lambda: SimpleNamespace(
            engine=engine, configuration=pubmed.ABIModule.Configuration()
        ),
    )
    with_pubmed = factory.workspace_actions(
        engine, SimpleNamespace(papers_root="phases_v2")
    )
    searches = with_pubmed.list_pubmed_searches()["searches"]
    assert store.downloaded_search in {s["search_id"] for s in searches}


def test_new_still_builds_the_assistant_when_its_services_cannot_be_built(
    monkeypatch,
):
    """Nexus builds every agent at start; one failing would stop them all."""
    import openalex

    def broken():
        raise RuntimeError("storage is down")

    model = chat(lambda messages: AIMessage("Hello"))
    module = SimpleNamespace(
        # No dataset or object storage: building the app's services fails.
        engine=SimpleNamespace(
            services=SimpleNamespace(
                model_registry=SimpleNamespace(get_default_chat_model=lambda: model)
            )
        ),
        configuration=SimpleNamespace(papers_root="phases_v2"),
    )
    monkeypatch.setattr(phases_v2.ABIModule, "get_instance", lambda: module)
    monkeypatch.setattr(pubmed.ABIModule, "get_instance", broken)
    monkeypatch.setattr(openalex.ABIModule, "get_instance", broken)

    agent = WorkspaceAssistantAgent.New()

    tools = {t.name: t for t in agent.tools}
    with pytest.raises(Unavailable, match="The workspace could not be reached"):
        tools["list_collections"].invoke({})
    with pytest.raises(
        Unavailable, match="PubMed could not be reached.*storage is down"
    ):
        tools["search_pubmed"].invoke({"query": "solitude"})
    # Nothing is kept from a failed build: the next call tries again.
    monkeypatch.setattr(pubmed.ABIModule, "get_instance", lambda: None.missing)
    with pytest.raises(Unavailable, match="PubMed could not be reached.*NoneType"):
        tools["search_pubmed"].invoke({"query": "solitude"})


# -- what it is told -------------------------------------------------------------


def test_the_instructions_cover_the_app_and_how_to_behave():
    for section in SECTIONS:
        assert f"- {section}:" in INSTRUCTIONS, section
    workflow = ["Collect papers", "Prepare prompts", "Run:", "Explore"]
    positions = [INSTRUCTIONS.index(step) for step in workflow]
    assert positions == sorted(positions), "the workflow is told in order"
    assert "Collections → Solitude studies → Run on this collection" in INSTRUCTIONS
    assert "You do not see the user's screen" in INSTRUCTIONS
    assert "Plain and short" in INSTRUCTIONS
    assert "explicit yes" in INSTRUCTIONS
    assert "You cannot delete, archive or remove anything" in INSTRUCTIONS
    assert "You cannot upload files" in INSTRUCTIONS
    assert "Collections → (the collection) → Upload PDFs" in INSTRUCTIONS
    assert "storage folder, with add_to_collection" in INSTRUCTIONS


# -- a conversation through the agent's graph --------------------------------------


def test_the_turn_marker_follows_the_latest_user_message():
    first = HumanMessage("Run it", id="m1")
    assert turn_marker([first, AIMessage("Sure?")]) == "m1"
    assert (
        turn_marker([first, AIMessage("Sure?"), HumanMessage("Yes", id="m2")]) == "m2"
    )
    assert turn_marker([AIMessage("Hello")]) is None
    unnamed = turn_marker([HumanMessage("Run it")])
    assert unnamed and unnamed != turn_marker([AIMessage("x"), HumanMessage("Run it")])


def test_the_turn_markers_name_the_latest_user_message_and_the_one_before():
    first, second = HumanMessage("Run it", id="m1"), HumanMessage("Yes", id="m2")
    assert turn_markers([]) == (None, None)
    assert turn_markers([first, AIMessage("Sure?")]) == ("m1", None)
    assert turn_markers(
        [first, AIMessage("Sure?"), second, HumanMessage("Ok", id="m3")]
    ) == ("m3", "m2")


def scripted_agent(env, script):
    return WorkspaceAssistantAgent(
        name=WorkspaceAssistantAgent.name,
        description=WorkspaceAssistantAgent.description,
        chat_model=chat(script),
        tools=build_tools(env.actions),
        agents=[],
        state=AgentSharedState(thread_id="chat-1"),
        configuration=AgentConfiguration(system_prompt=INSTRUCTIONS),
        memory=MemorySaver(),
        enable_default_tools=False,
    )


def test_a_run_is_queued_only_once_the_user_answers_yes(store):
    env = build_env(store, context=nexus_context)
    collection = env.actions.create_collection("Sleep", paper_ids=[PAPER])
    choices = run_choices(collection["collection_id"])
    seen = {}

    def tool_call(name, args):
        return AIMessage(
            "", tool_calls=[{"name": name, "args": args, "id": f"call-{len(seen)}"}]
        )

    def script(messages):
        last = messages[-1]
        seen[len(seen)] = last
        if isinstance(last, HumanMessage) and "Run Claims" in last.content:
            return tool_call("prepare_run", choices)
        if isinstance(last, ToolMessage) and last.name == "prepare_run":
            seen["token"] = json.loads(last.content)["confirmation_token"]
            # A model that skips asking: the tools must not let it through.
            return tool_call(
                "queue_run", dict(choices, confirmation_token=seen["token"])
            )
        if isinstance(last, HumanMessage) and last.content.startswith("Yes"):
            return tool_call(
                "queue_run", dict(choices, confirmation_token=seen["token"])
            )
        return AIMessage(f"{last.name} answered: {last.content}")

    agent = scripted_agent(env, script)
    chat_token = agent_chat_id.set("chat-1")
    user_token = agent_user_email.set("jeremy@naas.ai")
    try:
        first = agent.invoke(f"Run Claims on Sleep with {CLAIMS.name}")
        assert "has not answered yet" in first
        assert env.requests.requests == {}

        second = agent.invoke("Yes, go ahead")
    finally:
        agent_chat_id.reset(chat_token)
        agent_user_email.reset(user_token)

    assert '"queued": true' in second
    [request] = env.requests.requests.values()
    assert request.requested_by == "jeremy@naas.ai"
    assert request.prompt_ids == [CLAIMS.prompt_id]


def test_a_yes_given_messages_later_does_not_queue_the_run(store):
    """Asked in turn 1, another question in turn 2, "ok thanks" in turn 3."""
    env = build_env(store, context=nexus_context)
    collection = env.actions.create_collection("Sleep late", paper_ids=[PAPER])
    choices = run_choices(collection["collection_id"])
    seen = {}

    def script(messages):
        last = messages[-1]
        if isinstance(last, HumanMessage) and "Run Claims" in last.content:
            return AIMessage(
                "", tool_calls=[{"name": "prepare_run", "args": choices, "id": "c1"}]
            )
        if isinstance(last, ToolMessage) and last.name == "prepare_run":
            seen["token"] = json.loads(last.content)["confirmation_token"]
            return AIMessage("This queues one run. Shall I go ahead?")
        if isinstance(last, HumanMessage) and last.content.startswith("ok"):
            # A model that takes a later message for the yes.
            args = dict(choices, confirmation_token=seen["token"])
            return AIMessage(
                "", tool_calls=[{"name": "queue_run", "args": args, "id": "c2"}]
            )
        if isinstance(last, ToolMessage):
            return AIMessage(f"{last.name} answered: {last.content}")
        return AIMessage("You have one prompt, Claims.")

    agent = scripted_agent(env, script)
    chat_token = agent_chat_id.set("chat-1")
    user_token = agent_user_email.set("jeremy@naas.ai")
    try:
        agent.invoke(f"Run Claims on Sleep late with {CLAIMS.name}")
        agent.invoke("Which prompts do I have?")
        third = agent.invoke("ok thanks")
    finally:
        agent_chat_id.reset(chat_token)
        agent_user_email.reset(user_token)

    assert "more than once since" in third
    assert env.requests.requests == {}
