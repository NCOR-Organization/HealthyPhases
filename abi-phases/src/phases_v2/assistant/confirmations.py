"""Costly actions run only on a yes the user gave after seeing what they cost.

Each costly action is a pair of tools. *Prepare* describes the action and
issues a token; *execute* takes the same parameters with that token. The guard
lets execute through only when the token:

- exists, has not been used and has not expired (ten minutes);
- was issued for this action with exactly these parameters;
- was issued in this conversation, for this user;
- is the latest one prepared for this action in this conversation: preparing
  again (the user asked for something else) supersedes the earlier summary;
- was issued in an earlier turn: the user has written since, so they saw the
  summary before answering it;
- still describes what the action covers (its *basis*: a run's papers, the
  PMIDs a download fetches, how many papers an enrichment covers), for every
  action whose scope can change after it was prepared, so a yes is never
  applied to something that changed meanwhile.

A token is consumed by the first execute that passes these checks, before the
action runs, so two calls racing with one token cannot both act. A refused
execute leaves a valid token as it was, except when its basis changed: that
summary is stale and the action has to be prepared again.

Tokens live in this process. The API runs one, so this is exact; a restart
forgets pending tokens, which only means preparing again.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

#: How long a prepared action waits for its yes.
TOKEN_TTL_SECONDS = 600

#: The user message the assistant is answering. Set by the agent around each
#: batch of tool calls (see ``WorkspaceAssistantAgent.call_tools``), because a
#: tool is not given the conversation itself.
current_turn: ContextVar[str | None] = ContextVar(
    "phases_v2_assistant_turn", default=None
)


class ConfirmationRefused(ValueError):
    """An execute without a valid yes; the message says what to do instead."""


@dataclass(frozen=True)
class RequestContext:
    """Who is asking, in which conversation, answering which of their messages."""

    conversation: str
    user: str
    turn: str | None


@dataclass(frozen=True)
class Confirmation:
    token: str
    expires_in_minutes: int


@dataclass(frozen=True)
class _Pending:
    action: str
    fingerprint: str
    conversation: str
    user: str
    turn: str | None
    basis: str
    expires_at: float


def fingerprint(value: Any) -> str:
    """A stable digest of parameters (or a basis): same value, same digest."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ConfirmationGuard:
    def __init__(
        self,
        ttl_seconds: float = TOKEN_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        new_token: Callable[[], str] = lambda: secrets.token_urlsafe(18),
    ):
        self._ttl = ttl_seconds
        self._clock = clock
        self._new_token = new_token
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        #: Spent and superseded tokens until they would have expired, to say
        #: why one presented again is refused rather than call it unknown.
        self._spent: dict[str, float] = {}
        self._superseded: dict[str, float] = {}

    def issue(
        self,
        action: str,
        params: Mapping[str, Any],
        context: RequestContext,
        basis: Any = "",
    ) -> Confirmation:
        now = self._clock()
        token = self._new_token()
        with self._lock:
            self._forget_expired(now)
            for earlier, pending in list(self._pending.items()):
                if (pending.action, pending.conversation, pending.user) == (
                    action,
                    context.conversation,
                    context.user,
                ):
                    del self._pending[earlier]
                    self._superseded[earlier] = pending.expires_at
            self._pending[token] = _Pending(
                action=action,
                fingerprint=fingerprint(params),
                conversation=context.conversation,
                user=context.user,
                turn=context.turn,
                basis=fingerprint(basis),
                expires_at=now + self._ttl,
            )
        return Confirmation(token=token, expires_in_minutes=round(self._ttl / 60))

    def redeem(
        self,
        token: str,
        action: str,
        params: Mapping[str, Any],
        context: RequestContext,
        basis: Any = "",
    ) -> None:
        """Consume ``token`` for this exact action, or raise ``ConfirmationRefused``."""
        prepare = (
            f"Call prepare_{action} first, show the user its summary and ask them."
        )
        token = (token or "").strip()
        if not token:
            raise ConfirmationRefused(f"No confirmation token was given. {prepare}")
        now = self._clock()
        with self._lock:
            if token in self._spent:
                raise ConfirmationRefused(
                    "This confirmation token was already used; each yes covers one "
                    f"action. {prepare}"
                )
            if token in self._superseded:
                raise ConfirmationRefused(
                    "This confirmation token was replaced: the same kind of action "
                    "was prepared again since. Use the latest token, and only once "
                    "the user said yes to its summary."
                )
            pending = self._pending.get(token)
            if pending is None:
                raise ConfirmationRefused(
                    f"This confirmation token is not one this assistant issued. {prepare}"
                )
            if now >= pending.expires_at:
                del self._pending[token]
                raise ConfirmationRefused(
                    "This confirmation token has expired (they last "
                    f"{round(self._ttl / 60)} minutes). {prepare}"
                )
            if (pending.conversation, pending.user) != (
                context.conversation,
                context.user,
            ):
                raise ConfirmationRefused(
                    f"This confirmation token belongs to another conversation. {prepare}"
                )
            if pending.action != action or pending.fingerprint != fingerprint(params):
                raise ConfirmationRefused(
                    "This confirmation token was issued for a different action or "
                    "different parameters. Use exactly what was prepared, or "
                    f"prepare the new action. {prepare}"
                )
            if context.turn is None or context.turn == pending.turn:
                raise ConfirmationRefused(
                    "The user has not answered yet. Show them the summary, ask "
                    "whether to go ahead, and call this again only after they say yes."
                )
            if pending.basis != fingerprint(basis):
                del self._pending[token]
                raise ConfirmationRefused(
                    "What this action covers changed after it was prepared, so the "
                    f"summary the user agreed to is out of date. {prepare}"
                )
            del self._pending[token]
            self._spent[token] = pending.expires_at

    def _forget_expired(self, now: float) -> None:
        for token in [t for t, p in self._pending.items() if now >= p.expires_at]:
            del self._pending[token]
        for kept in (self._spent, self._superseded):
            for token in [t for t, until in kept.items() if now >= until]:
                del kept[token]
