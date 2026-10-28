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

from phases_v2.assistant.confirmations import RequestContext, current_turn


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
    )


def turn_marker(messages: Sequence[Any]) -> str | None:
    """Identifies the latest user message: a new message, a new marker."""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, HumanMessage):
            if message.id:
                return str(message.id)
            text = (
                message.content
                if isinstance(message.content, str)
                else repr(message.content)
            )
            return f"{index}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
    return None


def _graph_thread() -> str | None:
    """The thread the graph runs in, outside Nexus (the CLI chat, for example)."""
    from langchain_core.runnables.config import ensure_config

    thread = ensure_config().get("configurable", {}).get("thread_id")
    return str(thread) if thread else None
