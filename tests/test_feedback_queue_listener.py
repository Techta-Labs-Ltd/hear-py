from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import config.permission_scopes as permission_scopes
from src.alexa.runtime import AttrDict
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.controllers.confirmation import NoIntentHandler
from src.controllers.feedback import (
    FeedbackEnjoyedHandler,
    FeedbackNotEnjoyedHandler,
    SkipFeedbackHandler,
)
from src.controllers.report import ReportContentHandler
from src.middleware.feedback_gate import FeedbackGateHandler
from src.models.feedback import FeedbackService
from src.models.playback import Playback
from src.services.listener_sync import ListenerSyncService
from src.utils.content import ContentUtils
from src.utils.content_normalizer import ContentNormalizer


@pytest.mark.parametrize(
    "intent_name",
    [
        "AMAZON.NextIntent",
        "AMAZON.SkipIntent",
        "AMAZON.PreviousIntent",
        "AMAZON.PauseIntent",
        "AMAZON.ResumeIntent",
    ],
)
def test_pending_feedback_does_not_block_transport_intents(mock_handler_input, intent_name):
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "awaitingFeedback": True,
        "pendingFeedback": {
            "feedbackKey": "completed-1",
            "contentId": "completed-1",
            "completed": True,
        },
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {"type": "IntentRequest", "intent": {"name": intent_name, "slots": {}}}
    )
    assert FeedbackGateHandler(deps=ApplicationContainer()).can_handle(mock_handler_input) is False


@pytest.mark.parametrize(
    "request_type",
    [
        "PlaybackController.NextCommandIssued",
        "PlaybackController.PreviousCommandIssued",
        "PlaybackController.PauseCommandIssued",
        "PlaybackController.PlayCommandIssued",
    ],
)
def test_pending_feedback_does_not_block_controller_commands(mock_handler_input, request_type):
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "awaitingFeedback": True,
        "pendingFeedback": {
            "feedbackKey": "completed-1",
            "contentId": "completed-1",
            "completed": True,
        },
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({"type": request_type})
    assert FeedbackGateHandler(deps=ApplicationContainer()).can_handle(mock_handler_input) is False


def test_normalized_credit_prefers_real_organization_then_independent_creator():
    organization = ContentNormalizer.normalize_content_item(
        {
            "contentId": "content-org",
            "title": "Sport",
            "audioUrl": "https://cdn.hear.media/org.mp3",
            "creator": {"id": "creator-1", "name": "Individual Reporter"},
            "organization": {"id": "org-1", "name": "York Talking News"},
        }
    )
    assert ContentUtils.pick_content_credit(organization) == "York Talking News"
    independent = ContentNormalizer.normalize_content_item(
        {
            "contentId": "content-independent",
            "title": "Sport",
            "audioUrl": "https://cdn.hear.media/independent.mp3",
            "creator": {"id": "creator-2", "name": "David Beard"},
            "organization": {"id": "org-2", "name": "Independent Creator"},
        }
    )
    assert ContentUtils.pick_content_credit(independent) == "David Beard"


@pytest.mark.asyncio
async def test_enjoyed_feedback_uses_the_prompted_candidate_for_speech_and_sync(
    monkeypatch, mock_handler_input
):
    store = {
        **StateSchema.DEFAULT_STORE,
        "awaitingFeedback": True,
        "pendingFeedback": {
            "feedbackKey": "track-115",
            "contentId": "track-115",
            "publicationId": "publication-tynedale-weekly",
            "publicationTitle": "Tynedale weekly edition",
            "title": "TRACK115",
            "creatorId": "creator-tynedale",
            "creatorName": "Tynedale Talking Magazine",
            "category": "news",
            "listenedMs": 120000,
            "completed": True,
        },
        "feedbackContentTitle": "WhatsApp Ptt 2026-08-02 at 09.26.41",
        "feedbackCreatorId": "creator-other",
        "feedbackCreator": "Other Creator",
        "currentContentTitle": "Another current track",
        "followedCreators": [{"id": "creator-tynedale", "name": "Tynedale Talking Magazine"}],
    }
    mock_handler_input.attributes_manager.request_attributes["_store"] = store
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "intent": {"name": "FeedbackEnjoyedIntent", "slots": {}},
        }
    )
    await FeedbackEnjoyedHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "feedback on TRACK115 by Tynedale Talking Magazine" in spoken
    assert "WhatsApp Ptt" not in spoken
    assert (
        mock_handler_input.attributes_manager.request_attributes["_store"]["pendingFeedback"]
        is None
    )


def test_normalization_repairs_common_api_text_encoding():
    item = ContentNormalizer.normalize_content_item(
        {
            "contentId": "content-1",
            "title": "TodayÃ¢â‚¬â„¢s bulletin",
            "audioUrl": "https://cdn.hear.media/one.mp3",
            "organization": {
                "id": "org-1",
                "name": "Five Valley Sounds Ã¢â‚¬â€œ StroudÃ¢â‚¬â„¢s Talking Newspaper",
            },
        }
    )
    assert item["title"] == "Todayâ€™s bulletin"
    assert (
        ContentUtils.pick_content_credit(item)
        == "Five Valley Sounds â€“ Stroudâ€™s Talking Newspaper"
    )


def test_internal_short_identifier_is_not_used_as_spoken_title():
    item = ContentNormalizer.normalize_content_item(
        {
            "contentId": "content-1",
            "title": "00000006",
            "shortDescription": "A weekly sport update from York",
            "audioUrl": "https://cdn.hear.media/one.mp3",
        }
    )
    assert ContentUtils.content_title_for_speech(item) == "A weekly sport update from York"


def test_newest_feedback_replaces_and_discards_older_pending_item(mock_handler_input):
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "awaitingFeedback": True,
        "pendingFeedback": {
            "feedbackKey": "york-old",
            "contentId": "york-old",
            "title": "029_Car_park",
            "organizationName": "York Talking News",
            "playbackStartedAt": 100,
            "createdAt": 200,
            "completed": True,
        },
        "feedbackCandidates": [
            {
                "feedbackKey": "pendle-new",
                "contentId": "pendle-new",
                "title": "Pendle weekly update",
                "organizationName": "Pendle Voice",
                "playbackStartedAt": 300,
                "createdAt": 400,
                "completed": True,
            }
        ],
    }
    selected = FeedbackService.activate_best(mock_handler_input)
    store = mock_handler_input.attributes_manager.request_attributes["_store"]
    assert selected["contentId"] == "pendle-new"
    assert store["pendingFeedback"]["organizationName"] == "Pendle Voice"
    assert store["feedbackCandidates"] == []
    assert store["activeDialog"]["context"]["contentId"] == "pendle-new"


def test_delayed_old_completion_cannot_replace_newer_pending_feedback(
    mock_handler_input,
):
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "awaitingFeedback": True,
        "pendingFeedback": {
            "feedbackKey": "pendle-new",
            "contentId": "pendle-new",
            "playbackStartedAt": 300,
            "createdAt": 400,
            "completed": True,
        },
        "feedbackCandidates": [
            {
                "feedbackKey": "york-delayed",
                "contentId": "york-delayed",
                "playbackStartedAt": 100,
                "createdAt": 500,
                "completed": True,
            }
        ],
    }
    selected = FeedbackService.activate_best(mock_handler_input)
    store = mock_handler_input.attributes_manager.request_attributes["_store"]
    assert selected["contentId"] == "pendle-new"
    assert store["pendingFeedback"]["contentId"] == "pendle-new"
    assert store["feedbackCandidates"] == []


@pytest.mark.asyncio
async def test_queue_resolves_next_item_from_cached_catalog_without_api(
    monkeypatch, mock_handler_input
):
    cached = {
        "contentId": "content-2",
        "title": "Second story",
        "spokenTitle": "Second story",
        "audioUrl": "https://cdn.hear.media/two.mp3",
    }
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "browseCatalog": {"items": [cached]},
    }
    hear_client = AsyncMock()
    result = await Playback._resolve_content(
        mock_handler_input, "content-2", hear_client=hear_client
    )
    assert result == cached
    hear_client.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_negative_feedback_reports_without_resuming_rejected_play_request(
    monkeypatch, mock_handler_input
):
    store = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "awaitingFeedback": True,
        "pendingFeedback": {
            "feedbackKey": "old-content",
            "contentId": "old-content",
            "publicationId": "publication-old-weekly",
            "title": "Old bulletin",
            "creatorName": "Old Publisher",
        },
    }
    mock_handler_input.attributes_manager.request_attributes.update(
        {
            "_store": store,
            "_nlp": {
                "intent": "organization",
                "slots": {
                    "organizationIds": ["org-tnf"],
                    "organizationName": "Talking News Federation",
                    "residualQuery": "",
                },
            },
        }
    )
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "intent": {
                "name": "PlayByOrganizationIntent",
                "slots": {"organizationQuery": {"name": "organizationQuery", "value": "tnf"}},
            },
        }
    )
    FeedbackGateHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    mock_handler_input.request_envelope.request.intent = AttrDict(
        {"name": "FeedbackNotEnjoyedIntent", "slots": {}}
    )
    mock_handler_input.redispatch = AsyncMock(
        return_value={
            "outputSpeech": {
                "type": "SSML",
                "ssml": "<speak>I found 4 stories. Now playing one.</speak>",
            },
            "directives": [{"type": "AudioPlayer.Play"}],
        }
    )
    monkeypatch.setattr("src.controllers.feedback", AsyncMock())
    feedback_response = await FeedbackNotEnjoyedHandler(deps=ApplicationContainer()).handle(
        mock_handler_input
    )
    assert feedback_response is not None
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "say report this content" in spoken
    assert (
        mock_handler_input.attributes_manager.request_attributes["_store"]["awaitingReportDecision"]
        is True
    )
    mock_handler_input.request_envelope.request.intent = AttrDict(
        {"name": "ReportContentIntent", "slots": {}}
    )
    await ReportContentHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    mock_handler_input.redispatch.assert_not_awaited()
    assert (
        mock_handler_input.attributes_manager.request_attributes["_store"].get("deferredIntent")
        is None
    )
    report = mock_handler_input.attributes_manager.request_attributes["_store"]["reportHistory"][-1]
    assert report["subjectType"] == "content"
    assert report["contentId"] == "old-content"
    assert report["status"] == "pending"


@pytest.mark.asyncio
async def test_skip_feedback_does_not_restore_rejected_search_confirmation(
    monkeypatch, mock_handler_input
):
    payload = {
        "query": "update",
        "filter": {"categorySlugs": ["sport"], "organizationIds": ["org-ytn"]},
        "sort": "latest",
        "page": 0,
        "limit": 20,
    }
    mock_handler_input.attributes_manager.request_attributes.update(
        {
            "_store": {
                **StateSchema.DEFAULT_STORE,
                "onboardingComplete": True,
                "awaitingFeedback": True,
                "pendingFeedback": {
                    "feedbackKey": "old-content",
                    "contentId": "old-content",
                    "title": "Old bulletin",
                },
            },
            "_nlp": {
                "intent": "category",
                "confirmationLabel": "the latest sport update from York Talking News",
                "searchPayload": payload,
                "slots": {"searchPlan": payload},
            },
            "_pendingConfirmation": {
                "confirmText": "the latest sport update from York Talking News",
                "resolution": {
                    "requestId": "resolution-ytn",
                    "confirmationLabel": "the latest sport update from York Talking News",
                    "searchPayload": payload,
                    "expiresAt": 4102444800,
                },
            },
        }
    )
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {"type": "IntentRequest", "intent": {"name": "PlayContentIntent", "slots": {}}}
    )
    FeedbackGateHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    mock_handler_input.request_envelope.request.intent = AttrDict(
        {"name": "AMAZON.NoIntent", "slots": {}}
    )
    mock_handler_input.redispatch = AsyncMock(
        return_value={
            "outputSpeech": {
                "ssml": "<speak>Did you want me to play the latest sport update from York Talking News?</speak>"
            }
        }
    )
    monkeypatch.setattr("src.controllers.feedback", AsyncMock())
    await SkipFeedbackHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    mock_handler_input.redispatch.assert_not_awaited()
    assert (
        mock_handler_input.attributes_manager.request_attributes["_store"].get("deferredIntent")
        is None
    )


@pytest.mark.asyncio
async def test_plain_no_records_not_enjoyed_feedback(monkeypatch, mock_handler_input):
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "awaitingFeedback": True,
        "activeDialog": {
            "type": "feedback",
            "context": {"contentId": "old-content"},
            "createdAt": 1,
            "expiresAt": 4102444800,
        },
        "pendingFeedback": {"feedbackKey": "old-content", "contentId": "old-content"},
    }
    submit = AsyncMock()
    monkeypatch.setattr("src.models.feedback.FeedbackService.submit", submit)
    await NoIntentHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    submit.assert_awaited_once_with(mock_handler_input, "not_enjoyed")
    assert (
        mock_handler_input.attributes_manager.request_attributes["_store"]["awaitingFeedback"]
        is False
    )


@pytest.mark.asyncio
async def test_launch_listener_sync_uses_documented_profile(monkeypatch, mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "fullName": "Alex Hear",
        "userEmail": "alex@example.com",
        "userCity": "Manchester",
        "locality": "Manchester",
        "playCount": 3,
        "followedCreators": [
            {"id": "creator-1", "name": "Reader", "type": "creator"},
            {"id": "org-1", "name": "York Talking News", "type": "organization"},
        ],
    }
    mock_handler_input.request_envelope.context.System.user.permissions.scopes = {
        permission_scopes.PROFILE_NAME_READ: {"status": "GRANTED"},
        permission_scopes.PROFILE_EMAIL_READ: {"status": "GRANTED"},
    }
    sync = AsyncMock(return_value={"listenerId": "listener-1"})
    service = ListenerSyncService(SimpleNamespace(sync_listener=sync))
    assert await service.sync_for_launch(mock_handler_input)
    profile = sync.await_args.args[0]
    assert profile["alexaUserId"]
    assert profile["followedCreatorIds"] == ["creator-1"]
    assert profile["followedOrganizationIds"] == ["org-1"]
    assert profile["city"] == "Manchester"
    assert profile["locality"] == "Manchester"
    assert sync.await_args.kwargs["timeout_ms"] == 2500
