"""The guard in front of every costly action: one yes, for one exact action."""

import threading

import pytest

from phases_v2.assistant.confirmations import (
    ConfirmationGuard,
    ConfirmationRefused,
    RequestContext,
)

PARAMS = {"collection_id": "c1", "prompt_ids": ["p1"], "model_id": "m1"}
ASKED = RequestContext(conversation="chat-1", user="jeremy@naas.ai", turn="t1")
ANSWERED = RequestContext(conversation="chat-1", user="jeremy@naas.ai", turn="t2")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def guard(clock):
    return ConfirmationGuard(clock=clock)


def test_a_yes_in_a_later_message_lets_the_action_through_once(guard):
    token = guard.issue("run", PARAMS, ASKED, basis="papers-v1").token

    guard.redeem(token, "run", dict(PARAMS), ANSWERED, basis="papers-v1")

    with pytest.raises(ConfirmationRefused, match="already used"):
        guard.redeem(token, "run", PARAMS, ANSWERED, basis="papers-v1")


def test_tokens_are_unguessable_and_last_ten_minutes(guard):
    first = guard.issue("run", PARAMS, ASKED)
    second = guard.issue("run", PARAMS, ASKED)

    assert first.token != second.token
    assert len(first.token) >= 24
    assert first.expires_in_minutes == 10


@pytest.mark.parametrize("token", ["", "   ", None])
def test_no_token_is_refused(guard, token):
    with pytest.raises(ConfirmationRefused, match="No confirmation token.*prepare_run"):
        guard.redeem(token, "run", PARAMS, ANSWERED)


def test_a_token_the_guard_never_issued_is_refused(guard):
    guard.issue("run", PARAMS, ASKED)

    with pytest.raises(ConfirmationRefused, match="not one this assistant issued"):
        guard.redeem("made-up", "run", PARAMS, ANSWERED)


def test_an_expired_token_is_refused_and_forgotten(guard, clock):
    token = guard.issue("run", PARAMS, ASKED).token
    clock.now += 600

    with pytest.raises(ConfirmationRefused, match="expired"):
        guard.redeem(token, "run", PARAMS, ANSWERED)
    with pytest.raises(ConfirmationRefused, match="not one this assistant issued"):
        guard.redeem(token, "run", PARAMS, ANSWERED)


def test_a_token_just_before_expiry_still_works(guard, clock):
    token = guard.issue("run", PARAMS, ASKED).token
    clock.now += 599

    guard.redeem(token, "run", PARAMS, ANSWERED)


@pytest.mark.parametrize(
    "action, params",
    [
        ("pubmed_ingestion", PARAMS),
        ("run", dict(PARAMS, model_id="m2")),
        ("run", dict(PARAMS, prompt_ids=["p1", "p2"])),
        ("run", dict(PARAMS, collection_id="c2")),
    ],
)
def test_a_token_for_another_action_or_other_parameters_is_refused(
    guard, action, params
):
    token = guard.issue("run", PARAMS, ASKED).token

    with pytest.raises(ConfirmationRefused, match="different action or different"):
        guard.redeem(token, action, params, ANSWERED)
    # The mistake did not spend the yes: the prepared action still goes through.
    guard.redeem(token, "run", PARAMS, ANSWERED)


@pytest.mark.parametrize(
    "context",
    [
        RequestContext(conversation="chat-2", user="jeremy@naas.ai", turn="t2"),
        RequestContext(conversation="chat-1", user="maxime@naas.ai", turn="t2"),
    ],
)
def test_a_token_from_another_conversation_or_user_is_refused(guard, context):
    token = guard.issue("run", PARAMS, ASKED).token

    with pytest.raises(ConfirmationRefused, match="another conversation"):
        guard.redeem(token, "run", PARAMS, context)


def test_executing_in_the_turn_that_prepared_is_refused(guard):
    """The user has to have seen the summary and answered it."""
    token = guard.issue("run", PARAMS, ASKED).token

    with pytest.raises(ConfirmationRefused, match="has not answered yet"):
        guard.redeem(token, "run", PARAMS, ASKED)
    guard.redeem(token, "run", PARAMS, ANSWERED)


def test_without_a_known_turn_nothing_is_executed(guard):
    unknown = RequestContext(conversation="chat-1", user="jeremy@naas.ai", turn=None)
    token = guard.issue("run", PARAMS, unknown).token

    with pytest.raises(ConfirmationRefused, match="has not answered yet"):
        guard.redeem(token, "run", PARAMS, unknown)


def test_a_change_to_what_the_action_covers_needs_a_new_yes(guard):
    token = guard.issue("run", PARAMS, ASKED, basis="papers-v1").token

    with pytest.raises(ConfirmationRefused, match="changed after it was prepared"):
        guard.redeem(token, "run", PARAMS, ANSWERED, basis="papers-v2")
    with pytest.raises(ConfirmationRefused, match="not one this assistant issued"):
        guard.redeem(token, "run", PARAMS, ANSWERED, basis="papers-v1")


def test_parameter_order_does_not_matter_but_values_do(guard):
    token = guard.issue("run", {"a": 1, "b": [1, 2]}, ASKED).token

    guard.redeem(token, "run", {"b": [1, 2], "a": 1}, ANSWERED)


def test_two_racing_executes_act_once(guard):
    token = guard.issue("run", PARAMS, ASKED).token
    outcomes = []
    start = threading.Barrier(8)

    def execute():
        start.wait()
        try:
            guard.redeem(token, "run", PARAMS, ANSWERED)
            outcomes.append("ran")
        except ConfirmationRefused:
            outcomes.append("refused")

    threads = [threading.Thread(target=execute) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["ran"] + ["refused"] * 7


def test_expired_and_spent_tokens_are_not_kept_forever(guard, clock):
    spent = guard.issue("run", PARAMS, ASKED).token
    guard.redeem(spent, "run", PARAMS, ANSWERED)
    guard.issue("run", PARAMS, ASKED)
    clock.now += 601

    guard.issue("run", PARAMS, ASKED)

    assert len(guard._pending) == 1
    assert guard._spent == {}
