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
        ("SearchCreatorIntent", "searchQuery", "Pendle Voice Dalesman"),
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


@pytest.mark.parametrize(
    "spoken, expected_id",
    [
        ("play first", "creator-1"),
        ("the first one", "creator-1"),
        ("pick option two", "creator-2"),
        ("number 2", "creator-2"),
        ("select choice 3", "creator-3"),
        ("3rd option", "creator-3"),
    ],
)
def test_ambiguity_ordinal_variants_select_current_spoken_choice(
    mock_handler_input, spoken, expected_id
):
    pending = {
        "displayedCandidates": [
            {"type": "creator", "id": f"creator-{index}", "name": f"Creator {index}"}
            for index in range(1, 4)
        ]
    }

    candidate = DialogSelection.match_pending_candidate(
        mock_handler_input, pending, spoken
    )

    assert candidate["id"] == expected_id


def test_creator_location_fallback_keeps_city_capture_active(mock_handler_input):
    User.update(
        mock_handler_input,
        {
            "activeDialog": {
                "type": "creator_location",
                "context": {"slotName": "cityQuery"},
                "expiresAt": 4102444800,
            }
        },
    )
    _intent(mock_handler_input, "AMAZON.FallbackIntent")

    failure = DialogValidationPolicy.dialog_validation_failure(mock_handler_input)

    assert failure == {
        "dialogType": "creator_location",
        "speech": "Sorry, I didn't catch that city. Which city would you like me to find creators in?",
        "reprompt": "Sorry, I didn't catch that city. Which city would you like me to find creators in?",
        "captureSlot": True,
    }
    assert User.snapshot(mock_handler_input)["activeDialog"]["type"] == "creator_location"


def test_ambiguity_gibberish_does_not_select_an_ordinal(mock_handler_input):
    pending = {
        "displayedCandidates": [
            {"type": "creator", "id": f"creator-{index}", "name": f"Creator {index}"}
            for index in range(1, 4)
        ]
    }

    assert (
        DialogSelection.match_pending_candidate(
            mock_handler_input, pending, "something unrelated"
        )
        is None
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
    assert "Ok. What would you like to listen to instead?" in response["outputSpeech"]["ssml"]
    assert response["shouldEndSession"] is False


@pytest.mark.parametrize(
    "intent_name",
    [
        "TownCaptureIntent",
        "OpenDiscoveryIntent",
        "CarrierlessDiscoveryIntent",
        "SelectCreatorCityIntent",
        "SelectOrganizationIntent",
        "SelectPublicationSourceIntent",
        "PlayContentIntent",
    ],
)
def test_search_confirmation_rejects_discovery_reply_and_repeats_locked_question(
    mock_handler_input, intent_name
):
    pending = {"confirmationLabel": "content in Dorking"}
    User.update(
        mock_handler_input,
        {
            "awaitingSearchConfirmation": True,
            "pendingResolution": pending,
            "activeDialog": {
                "type": "search_confirmation",
                "context": pending,
            },
        },
    )
    _intent(mock_handler_input, intent_name)
    failure = DialogValidationPolicy.dialog_validation_failure(mock_handler_input)
    question = "Did you want me to play content in Dorking? Please say yes or no."
    assert failure == {
        "dialogType": "search_confirmation",
        "speech": question,
        "reprompt": question,
    }
    store = User.snapshot(mock_handler_input)
    assert store["awaitingSearchConfirmation"] is True
    assert store["pendingResolution"] == pending
    assert store["activeDialog"]["context"] == pending


def test_search_confirmation_uses_session_state_when_persistence_is_stale(
    mock_handler_input,
):
    pending = {
        "confirmationLabel": "content in Dorking",
        "searchPayload": {"query": "", "filter": {"city": "Dorking"}},
    }
    mock_handler_input.attributes_manager.request_attributes["_store"] = {}
    mock_handler_input.attributes_manager.get_session_attributes = lambda: {
        "awaitingSearchConfirmation": True,
        "pendingResolution": pending,
    }
    _intent(mock_handler_input, "PlayContentIntent")

    failure = DialogValidationPolicy.dialog_validation_failure(mock_handler_input)

    question = "Did you want me to play content in Dorking? Please say yes or no."
    assert failure == {
        "dialogType": "search_confirmation",
        "speech": question,
        "reprompt": question,
    }


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
    for allowed in (
        "TownCaptureIntent",
        "SetLocationIntent",
        "SearchLocationIntent",
        "AMAZON.NextIntent",
        "AMAZON.SkipIntent",
    ):
        _intent(mock_handler_input, allowed)
        assert DialogValidationPolicy.dialog_validation_failure(mock_handler_input) is None


def test_onboarding_town_confirmation_accepts_location_correction_and_skip(
    mock_handler_input,
):
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
    for allowed in (
        "AMAZON.YesIntent",
        "AMAZON.NoIntent",
        "TownCaptureIntent",
        "SetLocationIntent",
        "SearchLocationIntent",
        "AMAZON.NextIntent",
        "AMAZON.SkipIntent",
    ):
        _intent(mock_handler_input, allowed)
        assert DialogValidationPolicy.dialog_validation_failure(mock_handler_input) is None
    _intent(mock_handler_input, "SearchCreatorIntent")
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
            "name": "SearchCreatorIntent",
            "slots": {"searchQuery": {"value": "yes Gloucester"}},
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
