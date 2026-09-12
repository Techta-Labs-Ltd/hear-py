from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.alexa.runtime import AttrDict
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.controllers.browse import WhatsTrendingHandler
from src.models.playback import Playback


def test_resume_offer_requires_a_playable_https_url():
    state = {"contentId": "legacy-content", "status": "paused", "audioUrl": ""}
    assert not Playback.has_unfinished_playback({"activePlayback": state})
    state["audioUrl"] = "http://unsafe.example/audio.mp3"
    assert not Playback.has_unfinished_playback({"activePlayback": state})
    state["audioUrl"] = "https://cdn.hear.media/audio.mp3"
    assert Playback.has_unfinished_playback({"activePlayback": state})


@pytest.mark.asyncio
async def test_recommendation_intent_uses_availability_source_selection(
    monkeypatch, mock_handler_input
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "PlayRecommendationIntent", "slots": {}},
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    selection = {"outputSpeech": {"ssml": "<speak>Choose a source</speak>"}}
    begin_recommendations = AsyncMock(return_value=selection)
    monkeypatch.setattr(
        "src.models.availability.Availability.begin_recommendations",
        begin_recommendations,
    )
    handler = WhatsTrendingHandler(deps=ApplicationContainer())
    assert handler.can_handle(mock_handler_input)
    response = await handler.handle(mock_handler_input)

    assert response == selection
    begin_recommendations.assert_awaited_once()


@pytest.mark.asyncio
async def test_trending_intent_searches_and_plays_trending_content(
    monkeypatch, mock_handler_input
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "WhatsTrendingIntent", "slots": {}},
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    result = {
        "failed": False,
        "total_hits": 8,
        "results": [
            {
                "contentId": "content-1",
                "title": "Community update",
                "spokenTitle": "Community update",
                "creator": {"id": "creator-1", "name": "Hear Reporter"},
                "audioUrl": "https://cdn.hear.media/content-1.mp3",
            }
        ],
    }
    discover = AsyncMock(return_value=result)
    autoplay = AsyncMock(return_value={"directives": [{"type": "AudioPlayer.Play"}]})
    monkeypatch.setattr("src.models.search.Search.discover_content_via_search", discover)
    monkeypatch.setattr("src.models.search.Search.auto_play_first_from_search", autoplay)

    response = await WhatsTrendingHandler(deps=ApplicationContainer()).handle(
        mock_handler_input
    )

    options = autoplay.await_args.args[2]
    assert options["introOverride"] == "Here are 8 trending stories. Here's the first one."
    assert response["directives"][0]["type"] == "AudioPlayer.Play"
