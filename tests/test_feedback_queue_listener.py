from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.handlers.feedback.not_enjoyed import FeedbackNotEnjoyedHandler
from src.handlers.feedback.enjoyed import FeedbackEnjoyedHandler
from src.handlers.feedback.skip import SkipFeedbackHandler
from src.handlers.intents.social import ReportContentHandler
from src.handlers.intents.system import NoIntentHandler
from src.middleware.feedback_gate import FeedbackGateHandler
from src.runtime import AttrDict
from src.services.listeners import sync_listener_for_launch
from src.services.queue.advance import _resolve_content
from src.services.storage.persistence import DEFAULT_STORE
from src.utils.normalize_content_item import (
    content_title_for_speech,
    normalize_content_item,
    pick_content_credit,
)


def test_normalized_credit_prefers_real_organization_then_independent_creator():
    organization = normalize_content_item({
        "contentId": "content-org",
        "title": "Sport",
        "audioUrl": "https://cdn.hear.media/org.mp3",
        "creator": {"id": "creator-1", "name": "Individual Reporter"},
        "organization": {"id": "org-1", "name": "York Talking News"},
    })
    assert pick_content_credit(organization) == "York Talking News"

    independent = normalize_content_item({
        "contentId": "content-independent",
        "title": "Sport",
        "audioUrl": "https://cdn.hear.media/independent.mp3",
        "creator": {"id": "creator-2", "name": "David Beard"},
        "organization": {"id": "org-2", "name": "Independent Creator"},
    })
    assert pick_content_credit(independent) == "David Beard"


@pytest.mark.asyncio
async def test_enjoyed_feedback_uses_the_prompted_candidate_for_speech_and_sync(
    monkeypatch,
    mock_handler_input,
):
    dispatched = []
    store = {
        **DEFAULT_STORE,
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
        "followedCreators": [{
            "id": "creator-tynedale",
            "name": "Tynedale Talking Magazine",
        }],
    }
    mock_handler_input.attributes_manager.request_attributes["_store"] = store
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "intent": {"name": "FeedbackEnjoyedIntent", "slots": {}},
    })
    monkeypatch.setattr(
        "src.services.feedback.candidates.dispatch",
        lambda event, data: dispatched.append((event, data)),
    )

    await FeedbackEnjoyedHandler().handle(mock_handler_input)

    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "feedback on TRACK115 by Tynedale Talking Magazine" in spoken
    assert "WhatsApp Ptt" not in spoken
    assert dispatched == [("feedback.given", {
        "alexaUserId": "amzn1.ask.account.TEST",
        "feedbackKey": "track-115",
        "contentId": "track-115",
        "publicationId": "publication-tynedale-weekly",
        "publicationTitle": "Tynedale weekly edition",
        "creatorId": "creator-tynedale",
        "creatorName": "Tynedale Talking Magazine",
        "title": "TRACK115",
        "category": "news",
        "listenedMs": 120000,
        "feedback": "enjoyed",
        "timestamp": dispatched[0][1]["timestamp"],
    })]


def test_normalization_repairs_common_api_text_encoding():
    item = normalize_content_item({
        "contentId": "content-1",
        "title": "Todayâ€™s bulletin",
        "audioUrl": "https://cdn.hear.media/one.mp3",
        "organization": {
            "id": "org-1",
            "name": "Five Valley Sounds â€“ Stroudâ€™s Talking Newspaper",
        },
    })
    assert item["title"] == "Today’s bulletin"
    assert pick_content_credit(item) == "Five Valley Sounds – Stroud’s Talking Newspaper"


def test_internal_short_identifier_is_not_used_as_spoken_title():
    item = normalize_content_item({
        "contentId": "content-1",
        "title": "00000006",
        "shortDescription": "A weekly sport update from York",
        "audioUrl": "https://cdn.hear.media/one.mp3",
    })

    assert content_title_for_speech(item) == "A weekly sport update from York"


@pytest.mark.asyncio
async def test_queue_resolves_next_item_from_cached_catalog_without_api(
    monkeypatch,
    mock_handler_input,
):
    cached = {
        "contentId": "content-2",
        "title": "Second story",
        "spokenTitle": "Second story",
        "audioUrl": "https://cdn.hear.media/two.mp3",
    }
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "browseCatalog": {"items": [cached]},
    }
    api_search = AsyncMock()
    monkeypatch.setattr("src.services.queue.advance.search", api_search)

    result = await _resolve_content(mock_handler_input, "content-2")

    assert result == cached
    api_search.assert_not_awaited()


@pytest.mark.asyncio
async def test_negative_feedback_reports_then_resumes_deferred_play_request(
    monkeypatch,
    mock_handler_input,
):
    store = {
        **DEFAULT_STORE,
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
    mock_handler_input.attributes_manager.request_attributes.update({
        "_store": store,
        "_nlp": {
            "intent": "organization",
            "slots": {
                "organizationIds": ["org-tnf"],
                "organizationName": "Talking News Federation",
                "residualQuery": "",
            },
        },
    })
    mock_handler_input.request_envelope = AttrDict(
        mock_handler_input.request_envelope
    )
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "intent": {
            "name": "PlayByOrganizationIntent",
            "slots": {
                "organizationQuery": {
                    "name": "organizationQuery",
                    "value": "tnf",
                },
            },
        },
    })

    FeedbackGateHandler().handle(mock_handler_input)
    mock_handler_input.request_envelope.request.intent = AttrDict({
        "name": "FeedbackNotEnjoyedIntent",
        "slots": {},
    })
    mock_handler_input.redispatch = AsyncMock(return_value={
        "outputSpeech": {
            "type": "SSML",
            "ssml": "<speak>I found 4 stories. Now playing one.</speak>",
        },
        "directives": [{"type": "AudioPlayer.Play"}],
    })
    monkeypatch.setattr(
        "src.handlers.feedback.not_enjoyed.submit_feedback",
        AsyncMock(),
    )

    feedback_response = await FeedbackNotEnjoyedHandler().handle(mock_handler_input)

    assert feedback_response is not None
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "say report this content" in spoken
    assert mock_handler_input.attributes_manager.request_attributes["_store"][
        "awaitingReportDecision"
    ] is True
    mock_handler_input.request_envelope.request.intent = AttrDict({
        "name": "ReportContentIntent",
        "slots": {},
    })
    reports = []
    monkeypatch.setattr(
        "src.handlers.intents.social.dispatch",
        lambda event, data, options=None: reports.append((event, data, options)),
    )

    response = await ReportContentHandler().handle(mock_handler_input)

    mock_handler_input.redispatch.assert_awaited_once()
    assert mock_handler_input.request_envelope.request.intent.name == (
        "PlayByOrganizationIntent"
    )
    assert "Thanks for the feedback. I found 4 stories" in (
        response["outputSpeech"]["ssml"]
    )
    assert response["directives"][0]["type"] == "AudioPlayer.Play"
    assert reports[0][0] == "user.reported_content"
    assert reports[0][1]["contentId"] == "old-content"
    assert reports[0][1]["publicationId"] == "publication-old-weekly"


@pytest.mark.asyncio
async def test_skip_feedback_restores_exact_pending_search_confirmation(
    monkeypatch,
    mock_handler_input,
):
    payload = {
        "query": "update",
        "filter": {
            "categorySlugs": ["sport"],
            "organizationIds": ["org-ytn"],
        },
        "sort": "latest",
        "page": 0,
        "limit": 20,
    }
    mock_handler_input.attributes_manager.request_attributes.update({
        "_store": {
            **DEFAULT_STORE,
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
    })
    mock_handler_input.request_envelope = AttrDict(
        mock_handler_input.request_envelope
    )
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "intent": {"name": "PlayContentIntent", "slots": {}},
    })
    FeedbackGateHandler().handle(mock_handler_input)
    mock_handler_input.request_envelope.request.intent = AttrDict({
        "name": "AMAZON.NoIntent",
        "slots": {},
    })
    mock_handler_input.redispatch = AsyncMock(return_value={
        "outputSpeech": {
            "ssml": "<speak>Did you want me to play the latest sport update from York Talking News?</speak>",
        },
    })
    monkeypatch.setattr("src.handlers.feedback.skip.submit_feedback", AsyncMock())

    await SkipFeedbackHandler().handle(mock_handler_input)

    restored = mock_handler_input.attributes_manager.request_attributes[
        "_pendingConfirmation"
    ]
    assert restored["resolution"]["searchPayload"] == payload
    mock_handler_input.redispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_plain_no_skips_feedback_instead_of_recording_dislike(
    monkeypatch,
    mock_handler_input,
):
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "awaitingFeedback": True,
        "activeDialog": {
            "type": "feedback",
            "context": {"contentId": "old-content"},
            "createdAt": 1,
            "expiresAt": 4102444800,
        },
        "pendingFeedback": {
            "feedbackKey": "old-content",
            "contentId": "old-content",
        },
    }
    submit = AsyncMock()
    monkeypatch.setattr("src.handlers.feedback.skip.submit_feedback", submit)

    await NoIntentHandler().handle(mock_handler_input)

    submit.assert_awaited_once_with(mock_handler_input, "skipped")
    assert mock_handler_input.attributes_manager.request_attributes["_store"][
        "awaitingFeedback"
    ] is False


@pytest.mark.asyncio
async def test_launch_listener_sync_uses_documented_profile(monkeypatch, mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(
        mock_handler_input.request_envelope
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "userCity": "Manchester",
        "locality": "Manchester",
        "playCount": 3,
    }
    sync = AsyncMock(return_value={"listenerId": "listener-1"})
    monkeypatch.setattr("src.services.listeners.sync_listener", sync)

    assert await sync_listener_for_launch(mock_handler_input)

    profile = sync.await_args.args[0]
    assert profile["alexaUserId"]
    assert profile["city"] == "Manchester"
    assert profile["locality"] == "Manchester"
    assert sync.await_args.kwargs["timeout_ms"] == 2500
