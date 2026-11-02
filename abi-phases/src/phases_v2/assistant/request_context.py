"""Who the assistant is acting for, read from what Nexus sets on each request.

Nexus sets the conversation and the user on context variables before running
the agent (naas_abi_core's ``agent_chat_id`` and ``agent_user_*``). The turn
is set by the agent itself, from the conversation's latest user message.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import HumanMessage

from phases_v2.assistant.confirmations import (
    RequestContext,
    current_turn,
    previous_turn,
)


def nexus_context() -> RequestContext:
    from naas_abi_core.services.agent.context import (
        agent_chat_id,
        agent_user_email,
        agent_user_id,
    )

    return RequestContext(
        conversation=agent_chat_id.get() or _graph_thread() or "",
        user=agent_user_email.get() or agent_user_id.get() or "",
        turn=current_turn.get(),
        previous_turn=previous_turn.get(),
    )


def turn_marker(messages: Sequence[Any]) -> str | None:
    """Identifies the latest user message: a new message, a new marker."""
    return turn_markers(messages)[0]


def turn_markers(messages: Sequence[Any]) -> tuple[str | None, str | None]:
    """Markers of the latest user message and of the user message before it."""
    found = [
        _marker(index, message)
        for index, message in enumerate(messages)
        if isinstance(message, HumanMessage)
    ][-2:]
    if not found:
        return None, None
    return found[-1], found[0] if len(found) == 2 else None


def _marker(index: int, message: HumanMessage) -> str:
    if message.id:
        return str(message.id)
    text = (
        message.content if isinstance(message.content, str) else repr(message.content)
    )
    return f"{index}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _graph_thread() -> str | None:
    """The thread the graph runs in, outside Nexus (the CLI chat, for example)."""
    from langchain_core.runnables.config import ensure_config

    thread = ensure_config().get("configurable", {}).get("thread_id")
    return str(thread) if thread else None
