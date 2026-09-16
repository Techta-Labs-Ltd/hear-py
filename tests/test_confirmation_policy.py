from __future__ import annotations

import pytest

from src.models.confirmation import ConfirmationDecision, ConfirmationPolicy


def test_confirmation_policy_returns_typed_confirmation_without_an_alexa_request():
    decision = ConfirmationPolicy.decide(
        {
            "intent": "category",
            "status": "resolved",
            "slots": {"category": "sport"},
            "searchPayload": {"query": "sport", "filter": {"categorySlugs": ["sport"]}},
        },
        request_type="IntentRequest",
        alexa_intent="BrowseByCategoryIntent",
        raw_utterance="sport",
        validation_failed=False,
    )

    assert decision.kind == "confirm"
    assert decision.pending["confirmText"] == "content on sport"
    assert decision.pending["resolution"]["searchPayload"] == {
        "query": "sport",
        "filter": {"categorySlugs": ["sport"]},
    }


def test_confirmation_policy_returns_a_typed_clarification_for_missing_subject():
    decision = ConfirmationPolicy.decide(
        {"intent": "creator", "status": "resolved", "slots": {}},
        request_type="IntentRequest",
        alexa_intent="SearchCreatorIntent",
        raw_utterance=None,
        validation_failed=False,
    )

    assert decision.kind == "clarify"
    assert decision.clarification["reprompt"] == "Please say your request again."


def test_confirmation_policy_rejects_contradictory_decision_data():
    with pytest.raises(ValueError):
        ConfirmationDecision(kind="clear", pending={})
