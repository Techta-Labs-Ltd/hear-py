from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.alexa.runtime import ResponseBuilder
from src.clients.resolver import ResolverClient
from src.container import ApplicationContainer
from src.middleware.dialog_validation import (
    DialogValidationInterceptor,
    DialogValidationPolicy,
)
from src.middleware.resolver import ResolverInterceptor
from src.models.resolver_workflow import ResolverWorkflow
from src.models.user import User


def _intent(handler_input, name: str) -> None:
    handler_input.request_envelope["request"] = {
        "type": "IntentRequest",
        "intent": {"name": name, "slots": {}},
    }


@pytest.mark.parametrize(
    "intent_name",
    [
        "AMAZON.NoIntent",
        "SkipFeedbackIntent",
        "AMAZON.NextIntent",
        "AMAZON.PreviousIntent",
        "ShowPreviousBrowseIntent",
    ],
)
def test_ambiguity_allows_dismissal_intents(mock_handler_input, intent_name):
    pending = {
        "candidates": [
            {"name": "Nailsea", "id": "one"},
            {"name": "Hailey", "id": "two"},
        ]
    }
    User.update(
        mock_handler_input,
        {
            "pendingAmbiguity": pending,
            "activeDialog": {"type": "ambiguity", "context": pending},
        },
    )
    _intent(mock_handler_input, intent_name)
    failure = DialogValidationPolicy.dialog_validation_failure(mock_handler_input)
    assert failure is None
    assert (
        mock_handler_input.attributes_manager.request_attributes["_store"]["pendingAmbiguity"]
        == pending
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("intent_name", ["AMAZON.NoIntent", "SkipFeedbackIntent"])
async def test_ambiguity_dismissal_clears_dialog_and_keeps_session_open(
    mock_handler_input, intent_name
):
    from src.controllers.confirmation import NoIntentHandler
    from src.controllers.feedback import SkipFeedbackHandler
    from src.models.user import User

    pending = {"candidates": [{"name": "Pendle Voice", "id": "one"}]}
    playback_queue = {
        "orderedContentIds": ["content-1", "content-2"],
        "currentIndex": 0,
    }
    User.update(
        mock_handler_input,
        {
            "pendingAmbiguity": pending,
            "activeDialog": {"type": "ambiguity", "context": pending},
            "playbackQueue": playback_queue,
        },
    )
    _intent(mock_handler_input, intent_name)
    mock_handler_input.response_builder = ResponseBuilder()
    handler = (
        NoIntentHandler(deps=ApplicationContainer())
        if intent_name == "AMAZON.NoIntent"
        else SkipFeedbackHandler(deps=ApplicationContainer())
    )
    response = await handler.handle(mock_handler_input)
    store = User.snapshot(mock_handler_input)
    assert store["pendingAmbiguity"] is None
    assert store["activeDialog"] is None
    assert store["playbackQueue"] == playback_queue
    assert "No problem" in response["outputSpeech"]["ssml"]
    assert response["shouldEndSession"] is False


def test_search_confirmation_rejects_new_search(mock_handler_input):
    User.update(
        mock_handler_input,
        {
            "awaitingSearchConfirmation": True,
            "pendingResolution": {"confirmationLabel": "Daily Sermons"},
            "activeDialog": {
                "type": "search_confirmation",
                "context": {"confirmationLabel": "Daily Sermons"},
            },
        },
    )
    _intent(mock_handler_input, "PlayContentIntent")
    failure = DialogValidationPolicy.dialog_validation_failure(mock_handler_input)
    assert failure["dialogType"] == "search_confirmation"
    assert "Daily Sermons" in failure["speech"]
    assert "yes or no" in failure["speech"]


def test_feedback_allows_ratings_and_transport_but_rejects_search(mock_handler_input):
    User.update(
        mock_handler_input,
        {
            "awaitingFeedback": True,
            "pendingFeedback": {"completed": True},
            "activeDialog": {"type": "feedback", "context": {}},
        },
    )
    for allowed in ("FeedbackEnjoyedIntent", "AMAZON.YesIntent", "AMAZON.NextIntent"):
        _intent(mock_handler_input, allowed)
        assert DialogValidationPolicy.dialog_validation_failure(mock_handler_input) is None
    _intent(mock_handler_input, "PlayContentIntent")
    assert (
        DialogValidationPolicy.dialog_validation_failure(mock_handler_input)["dialogType"]
        == "feedback"
    )


def test_report_decision_allows_report_and_skip(mock_handler_input):
    User.update(
        mock_handler_input,
        {
            "awaitingReportDecision": True,
            "activeDialog": {"type": "report_decision", "context": {}},
        },
    )
    for allowed in ("ReportContentIntent", "SkipFeedbackIntent", "AMAZON.NoIntent"):
        _intent(mock_handler_input, allowed)
        assert DialogValidationPolicy.dialog_validation_failure(mock_handler_input) is None
    _intent(mock_handler_input, "PlayContentIntent")
    assert (
        DialogValidationPolicy.dialog_validation_failure(mock_handler_input)["dialogType"]
        == "report_decision"
    )


def test_onboarding_permission_accepts_spoken_location_reply(mock_handler_input):
    User.update(
        mock_handler_input,
        {
            "onboardingStage": "ask_permission",
            "activeDialog": {
                "type": "onboarding",
                "context": {"stage": "ask_permission"},
            },
        },
    )
    _intent(mock_handler_input, "TownCaptureIntent")
    failure = DialogValidationPolicy.dialog_validation_failure(mock_handler_input)
    assert failure is None


def test_onboarding_town_confirmation_accepts_only_yes_or_no(mock_handler_input):
    User.update(
        mock_handler_input,
        {
            "onboardingStage": "await_location_confirm",
            "activeDialog": {
                "type": "onboarding",
                "context": {"stage": "await_location_confirm"},
            },
        },
    )
    for allowed in ("AMAZON.YesIntent", "AMAZON.NoIntent"):
        _intent(mock_handler_input, allowed)
        assert DialogValidationPolicy.dialog_validation_failure(mock_handler_input) is None
    _intent(mock_handler_input, "PlayByCreatorIntent")
    failure = DialogValidationPolicy.dialog_validation_failure(mock_handler_input)
    assert "correct city" in failure["speech"]


def test_current_onboarding_stage_overrides_stale_permission_dialog(mock_handler_input):
    User.update(
        mock_handler_input,
        {
            "onboardingStage": "ask_town",
            "activeDialog": {
                "type": "onboarding",
                "context": {"stage": "ask_permission"},
            },
        },
    )
    _intent(mock_handler_input, "TownCaptureIntent")
    assert DialogValidationPolicy.dialog_validation_failure(mock_handler_input) is None


def test_completed_onboarding_ignores_stale_onboarding_dialog(mock_handler_input):
    User.update(
        mock_handler_input,
        {
            "onboardingComplete": True,
            "onboardingStage": None,
            "activeDialog": {
                "type": "onboarding",
                "context": {"stage": "ask_permission"},
            },
        },
    )
    _intent(mock_handler_input, "PlayContentIntent")
    assert DialogValidationPolicy.dialog_validation_failure(mock_handler_input) is None


@pytest.mark.asyncio
async def test_invalid_onboarding_reply_never_reaches_resolver(monkeypatch, mock_handler_input):
    User.update(
        mock_handler_input,
        {
            "onboardingStage": "ask_permission",
            "activeDialog": {
                "type": "onboarding",
                "context": {"stage": "ask_permission"},
            },
        },
    )
    mock_handler_input.request_envelope["request"] = {
        "type": "IntentRequest",
        "intent": {
            "name": "PlayByCreatorIntent",
            "slots": {"creatorQuery": {"value": "yes Gloucester"}},
        },
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    DialogValidationInterceptor().process(mock_handler_input)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    resolve.assert_not_awaited()
    assert mock_handler_input.attributes_manager.request_attributes.get("_nlp") is None


def test_latest_content_intent_reconstructs_sort_for_resolver(mock_handler_input):
    topic_slot = MagicMock()
    topic_slot.value = "news content in Wakefield"
    intent = MagicMock()
    intent.get.return_value = {"topic": topic_slot}
    request = MagicMock()
    request.intent = intent
    envelope = MagicMock()
    envelope.request = request
    mock_handler_input.request_envelope = envelope
    assert (
        ResolverWorkflow._extract_raw_utterance(mock_handler_input, "PlayLatestContentIntent")
        == "play latest news content in Wakefield"
    )


def test_content_intent_preserves_raw_slot_for_internal_state(mock_handler_input):
    topic_slot = MagicMock()
    topic_slot.value = "tnf"
    intent = MagicMock()
    intent.get.return_value = {"topic": topic_slot}
    request = MagicMock()
    request.intent = intent
    envelope = MagicMock()
    envelope.request = request
    mock_handler_input.request_envelope = envelope
    assert ResolverWorkflow._extract_raw_utterance(mock_handler_input, "PlayContentIntent") == "tnf"
