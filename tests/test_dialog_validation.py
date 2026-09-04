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
from src.models.dialog import DialogSelection
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
@pytest.mark.parametrize(
    ("intent_name", "slot_name", "spoken_name"),
    [
        ("PlayByCreatorIntent", "creatorQuery", "Pendle Voice Dalesman"),
        ("PlayContentIntent", "topic", "Pendle Voice Dalesman"),
        ("PlayContentIntent", "topic", "Pendle Voice Dale's Men"),
    ],
)
async def test_candidate_name_bypasses_ambiguity_gate_and_resolves_locally(
    monkeypatch,
    mock_handler_input,
    intent_name,
    slot_name,
    spoken_name,
):
    candidate = {
        "type": "creator",
        "id": "creator-dalesman",
        "name": "Pendle Voice Dalesman",
    }
    pending = {
        "intent": "creator",
        "searchPayload": {"query": "", "filter": {}},
        "slots": {},
        "candidates": [
            candidate,
            {
                "type": "creator",
                "id": "creator-lancashire",
                "name": "Pendle Voice Lancashire Life",
            },
        ],
        "expiresAt": 4102444800,
    }
    User.update(
        mock_handler_input,
        {
            "pendingAmbiguity": pending,
            "activeDialog": {"type": "ambiguity", "context": pending},
        },
    )
    mock_handler_input.request_envelope["request"] = {
        "type": "IntentRequest",
        "intent": {
            "name": intent_name,
            "slots": {
                slot_name: {
                    "name": slot_name,
                    "value": spoken_name,
                }
            },
        },
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    DialogValidationInterceptor().process(mock_handler_input)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    resolve.assert_not_awaited()
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["ambiguityResolution"] is True
    assert nlp["searchPayload"]["filter"] == {"creatorIds": ["creator-dalesman"]}
    assert User.snapshot(mock_handler_input)["pendingAmbiguity"] is None


def test_shared_asr_prefix_does_not_choose_an_arbitrary_candidate(mock_handler_input):
    pending = {
        "candidates": [
            {
                "type": "creator",
                "id": "creator-dalesman",
                "name": "Pendle Voice Dalesman",
            },
            {
                "type": "creator",
                "id": "creator-lancashire",
                "name": "Pendle Voice Lancashire Life",
            },
        ],
        "expiresAt": 4102444800,
    }
    User.update(
        mock_handler_input,
        {
            "pendingAmbiguity": pending,
            "activeDialog": {"type": "ambiguity", "context": pending},
        },
    )
    mock_handler_input.request_envelope["request"] = {
        "type": "IntentRequest",
        "intent": {
            "name": "PlayContentIntent",
            "slots": {"topic": {"name": "topic", "value": "pendu voice"}},
        },
    }

    failure = DialogValidationPolicy.dialog_validation_failure(mock_handler_input)

    assert failure["dialogType"] == "ambiguity"


def test_unrelated_name_remains_blocked_during_ambiguity(mock_handler_input):
    pending = {
        "candidates": [
            {
                "type": "creator",
                "id": "creator-dalesman",
                "name": "Pendle Voice Dalesman",
            }
        ],
        "expiresAt": 4102444800,
    }
    User.update(
        mock_handler_input,
        {
            "pendingAmbiguity": pending,
            "activeDialog": {"type": "ambiguity", "context": pending},
        },
    )
    mock_handler_input.request_envelope["request"] = {
        "type": "IntentRequest",
        "intent": {
            "name": "PlayContentIntent",
            "slots": {"topic": {"name": "topic", "value": "jazz"}},
        },
    }

    failure = DialogValidationPolicy.dialog_validation_failure(mock_handler_input)

    assert failure["dialogType"] == "ambiguity"


def test_final_ambiguity_page_repeats_current_ordinals_without_more(mock_handler_input):
    candidates = [
        {"type": "creator", "id": f"creator-{index}", "name": f"Source {index}"}
        for index in range(1, 6)
    ]
    pending = {
        "candidates": candidates,
        "choiceCandidates": candidates,
        "displayedCandidates": candidates[3:],
        "spokenCandidateOffset": 5,
        "candidatePagination": {
            "currentPage": 1,
            "totalPages": 2,
            "totalHits": 5,
            "limit": 3,
        },
    }
    User.update(
        mock_handler_input,
        {
            "pendingAmbiguity": pending,
            "activeDialog": {"type": "ambiguity", "context": pending},
        },
    )
    mock_handler_input.request_envelope["request"] = {
        "type": "IntentRequest",
        "intent": {
            "name": "PlayContentIntent",
            "slots": {"topic": {"name": "topic", "value": "unrelated"}},
        },
    }

    failure = DialogValidationPolicy.dialog_validation_failure(mock_handler_input)

    assert "First, 4" in failure["speech"]
    assert "Second, 5" in failure["speech"]
    assert "show more" not in failure["speech"]
    assert "show more" not in failure["reprompt"]
    assert "say previous" in failure["reprompt"]


def test_ambiguity_name_matching_is_limited_to_the_current_page(mock_handler_input):
    candidates = [
        {"type": "creator", "id": f"creator-{index}", "name": f"Source {index}"}
        for index in range(1, 6)
    ]
    pending = {
        "candidates": candidates,
        "choiceCandidates": candidates,
        "displayedCandidates": candidates[3:],
        "spokenCandidateOffset": 5,
    }
    mock_handler_input.request_envelope["request"] = {
        "type": "IntentRequest",
        "intent": {
            "name": "ClarifySelectionIntent",
            "slots": {"selection": {"name": "selection", "value": "Source 1"}},
        },
    }

    assert DialogSelection.match_pending_candidate(
        mock_handler_input, pending, "Source 1"
    ) is None

    mock_handler_input.request_envelope["request"]["intent"]["slots"]["selection"][
        "value"
    ] = "Source 4"
    assert (
        DialogSelection.match_pending_candidate(mock_handler_input, pending, "Source 4")[
            "id"
        ]
        == "creator-4"
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


def test_resume_validation_repeats_publication_title(mock_handler_input):
    context = {
        "contentId": "track-2",
        "title": "Second track",
        "publicationId": "publication-1",
        "subjectTitle": "Weekly publication",
        "subjectType": "publication",
    }
    User.update(
        mock_handler_input,
        {
            "awaitingResume": True,
            "activePlayback": context,
            "activeDialog": {"type": "resume", "context": context},
        },
    )
    _intent(mock_handler_input, "PlayContentIntent")

    failure = DialogValidationPolicy.dialog_validation_failure(mock_handler_input)

    assert "Weekly publication" in failure["speech"]
    assert "Weekly publication" in failure["reprompt"]
    assert "that recording" not in failure["speech"]


def test_feedback_allows_ratings_and_transport_but_rejects_search(mock_handler_input):
    User.update(
        mock_handler_input,
        {
            "awaitingFeedback": True,
            "pendingFeedback": {"completed": True},
            "activeDialog": {"type": "feedback", "context": {}},
        },
    )
    for allowed in (
        "FeedbackEnjoyedIntent",
        "RateContentIntent",
        "AMAZON.YesIntent",
        "AMAZON.NextIntent",
        "SetPlaybackSpeedIntent",
        "IncreaseSpeedIntent",
        "DecreaseSpeedIntent",
        "HearNotificationsIntent",
    ):
        _intent(mock_handler_input, allowed)
        assert DialogValidationPolicy.dialog_validation_failure(mock_handler_input) is None
    _intent(mock_handler_input, "PlayContentIntent")
    assert (
        DialogValidationPolicy.dialog_validation_failure(mock_handler_input)["dialogType"]
        == "feedback"
    )


def test_notification_dialog_allows_playback_controls_but_rejects_search(
    mock_handler_input,
):
    context = {"question": "You have a new update. Would you like to listen now?"}
    User.update(
        mock_handler_input,
        {
            "awaitingNotificationChoice": True,
            "activeDialog": {"type": "notification", "context": context},
        },
    )
    for allowed in (
        "AMAZON.YesIntent",
        "AMAZON.NoIntent",
        "AMAZON.PauseIntent",
        "AMAZON.ResumeIntent",
        "IncreaseSpeedIntent",
        "DecreaseSpeedIntent",
        "RewindIntent",
        "FastForwardIntent",
    ):
        _intent(mock_handler_input, allowed)
        assert DialogValidationPolicy.dialog_validation_failure(mock_handler_input) is None
    _intent(mock_handler_input, "PlayContentIntent")
    failure = DialogValidationPolicy.dialog_validation_failure(mock_handler_input)
    assert failure["dialogType"] == "notification"
    assert "new update" in failure["speech"]


def test_feedback_validation_repeats_publication_title(mock_handler_input):
    pending = {
        "feedbackKey": "publication:publication-1",
        "subjectType": "publication",
        "publicationId": "publication-1",
        "publicationTitle": "Weekly publication",
        "completed": True,
    }
    User.update(
        mock_handler_input,
        {
            "awaitingFeedback": True,
            "pendingFeedback": pending,
            "activeDialog": {"type": "feedback", "context": pending},
        },
    )
    _intent(mock_handler_input, "PlayContentIntent")

    failure = DialogValidationPolicy.dialog_validation_failure(mock_handler_input)

    assert "Weekly publication" in failure["speech"]
    assert "Weekly publication" in failure["reprompt"]
    assert "that track" not in failure["speech"]


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
