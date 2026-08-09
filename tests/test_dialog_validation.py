from __future__ import annotations

from src.middleware.dialog_validation import dialog_validation_failure
from src.middleware.dialog_validation import DialogValidationInterceptor
from src.middleware.resolver import ResolverInterceptor
from src.clients.resolver import ResolverClient
from src.services.store import update_store
from unittest.mock import AsyncMock
import pytest


def _intent(handler_input, name: str) -> None:
    handler_input.request_envelope["request"] = {
        "type": "IntentRequest",
        "intent": {"name": name, "slots": {}},
    }


def test_ambiguity_rejects_no_without_clearing_choices(mock_handler_input):
    pending = {
        "candidates": [
            {"name": "Nailsea", "id": "one"},
            {"name": "Hailey", "id": "two"},
        ],
    }
    update_store(mock_handler_input, {
        "pendingAmbiguity": pending,
        "activeDialog": {"type": "ambiguity", "context": pending},
    })
    _intent(mock_handler_input, "AMAZON.NoIntent")

    failure = dialog_validation_failure(mock_handler_input)

    assert failure["dialogType"] == "ambiguity"
    assert "first one" in failure["speech"]
    assert mock_handler_input.attributes_manager.request_attributes["_store"]["pendingAmbiguity"] == pending


def test_search_confirmation_rejects_new_search(mock_handler_input):
    update_store(mock_handler_input, {
        "awaitingSearchConfirmation": True,
        "pendingResolution": {"confirmationLabel": "Daily Sermons"},
        "activeDialog": {
            "type": "search_confirmation",
            "context": {"confirmationLabel": "Daily Sermons"},
        },
    })
    _intent(mock_handler_input, "PlayContentIntent")

    failure = dialog_validation_failure(mock_handler_input)

    assert failure["dialogType"] == "search_confirmation"
    assert "Daily Sermons" in failure["speech"]
    assert "yes or no" in failure["speech"]


def test_feedback_allows_ratings_and_transport_but_rejects_search(mock_handler_input):
    update_store(mock_handler_input, {
        "awaitingFeedback": True,
        "pendingFeedback": {"completed": True},
        "activeDialog": {"type": "feedback", "context": {}},
    })

    for allowed in ("FeedbackEnjoyedIntent", "AMAZON.YesIntent", "AMAZON.NextIntent"):
        _intent(mock_handler_input, allowed)
        assert dialog_validation_failure(mock_handler_input) is None

    _intent(mock_handler_input, "PlayContentIntent")
    assert dialog_validation_failure(mock_handler_input)["dialogType"] == "feedback"


def test_report_decision_allows_report_and_skip(mock_handler_input):
    update_store(mock_handler_input, {
        "awaitingReportDecision": True,
        "activeDialog": {"type": "report_decision", "context": {}},
    })
    for allowed in ("ReportContentIntent", "SkipFeedbackIntent", "AMAZON.NoIntent"):
        _intent(mock_handler_input, allowed)
        assert dialog_validation_failure(mock_handler_input) is None

    _intent(mock_handler_input, "PlayContentIntent")
    assert dialog_validation_failure(mock_handler_input)["dialogType"] == "report_decision"


def test_onboarding_permission_rejects_mixed_location_reply(mock_handler_input):
    update_store(mock_handler_input, {
        "onboardingStage": "ask_permission",
        "activeDialog": {
            "type": "onboarding",
            "context": {"stage": "ask_permission"},
        },
    })
    _intent(mock_handler_input, "TownCaptureIntent")

    failure = dialog_validation_failure(mock_handler_input)

    assert failure["dialogType"] == "onboarding"
    assert "device location" in failure["speech"]
    assert "yes or no" in failure["speech"]


def test_onboarding_town_confirmation_accepts_only_yes_or_no(mock_handler_input):
    update_store(mock_handler_input, {
        "onboardingStage": "await_location_confirm",
        "activeDialog": {
            "type": "onboarding",
            "context": {"stage": "await_location_confirm"},
        },
    })
    for allowed in ("AMAZON.YesIntent", "AMAZON.NoIntent"):
        _intent(mock_handler_input, allowed)
        assert dialog_validation_failure(mock_handler_input) is None

    _intent(mock_handler_input, "PlayByCreatorIntent")
    failure = dialog_validation_failure(mock_handler_input)
    assert "correct city" in failure["speech"]


def test_current_onboarding_stage_overrides_stale_permission_dialog(mock_handler_input):
    update_store(mock_handler_input, {
        "onboardingStage": "ask_town",
        "activeDialog": {
            "type": "onboarding",
            "context": {"stage": "ask_permission"},
        },
    })
    _intent(mock_handler_input, "TownCaptureIntent")

    assert dialog_validation_failure(mock_handler_input) is None


def test_completed_onboarding_ignores_stale_onboarding_dialog(mock_handler_input):
    update_store(mock_handler_input, {
        "onboardingComplete": True,
        "onboardingStage": None,
        "activeDialog": {
            "type": "onboarding",
            "context": {"stage": "ask_permission"},
        },
    })
    _intent(mock_handler_input, "PlayContentIntent")

    assert dialog_validation_failure(mock_handler_input) is None


@pytest.mark.asyncio
async def test_invalid_onboarding_reply_never_reaches_resolver(
    monkeypatch, mock_handler_input,
):
    update_store(mock_handler_input, {
        "onboardingStage": "ask_permission",
        "activeDialog": {
            "type": "onboarding",
            "context": {"stage": "ask_permission"},
        },
    })
    mock_handler_input.request_envelope["request"] = {
        "type": "IntentRequest",
        "intent": {
            "name": "PlayByCreatorIntent",
            "slots": {
                "creatorQuery": {"value": "yes Gloucester"},
            },
        },
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    DialogValidationInterceptor().process(mock_handler_input)
    await ResolverInterceptor().process(mock_handler_input)

    resolve.assert_not_awaited()
    assert mock_handler_input.attributes_manager.request_attributes.get("_nlp") is None
