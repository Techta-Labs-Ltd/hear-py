from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.handlers.feedback.not_enjoyed import FeedbackNotEnjoyedHandler
from src.middleware.feedback_gate import FeedbackGateHandler
from src.runtime import AttrDict
from src.services.listeners import sync_listener_for_launch
from src.services.queue.advance import _resolve_content
from src.services.storage.persistence import DEFAULT_STORE
from src.utils.normalize_content_item import (
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
async def test_feedback_answer_resumes_the_deferred_play_request(
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

    response = await FeedbackNotEnjoyedHandler().handle(mock_handler_input)

    mock_handler_input.redispatch.assert_awaited_once()
    assert mock_handler_input.request_envelope.request.intent.name == (
        "PlayByOrganizationIntent"
    )
    assert "Thanks for the feedback. I found 4 stories" in (
        response["outputSpeech"]["ssml"]
    )
    assert response["directives"][0]["type"] == "AudioPlayer.Play"


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
