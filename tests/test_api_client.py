from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.handlers.intents.play import auto_play_first_from_search
from src.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.services.api.client import (
    _build_alexa_relative_path,
    _build_alexa_search_path,
    _build_api_path,
)
from src.services.playback.start import start_playback


def test_search_path_applies_configured_prefix_once(monkeypatch):
    monkeypatch.setattr(
        "src.services.api.client.settings.HEAR_API_PATH_PREFIX",
        "alexa",
    )

    assert _build_api_path(_build_alexa_search_path()) == "/alexa/search"


def test_search_path_uses_legacy_alexa_route_without_prefix(monkeypatch):
    monkeypatch.setattr(
        "src.services.api.client.settings.HEAR_API_PATH_PREFIX",
        "",
    )

    assert _build_api_path(_build_alexa_search_path()) == "/alexa/search"


def test_location_path_applies_configured_prefix_once(monkeypatch):
    monkeypatch.setattr(
        "src.services.api.client.settings.HEAR_API_PATH_PREFIX",
        "alexa",
    )

    assert _build_api_path(_build_alexa_relative_path("location")) == "/alexa/location"


@pytest.mark.asyncio
async def test_real_search_shape_reaches_playback_without_catalog_call_error(
    monkeypatch,
    mock_handler_input,
):
    expected = {"response": "play"}
    start = AsyncMock(return_value=expected)
    monkeypatch.setattr("src.handlers.intents.play.start_playback", start)
    result = await auto_play_first_from_search(
        mock_handler_input,
        {
            "results": [{
                "contentId": "content-1",
                "title": "Morning update",
                "spokenTitle": "Morning update",
                "creator": "Shetland Life",
                "audioUrl": "https://cdn.hear.media/audio/content-1.mp3",
                "playbackSpeeds": [],
            }],
            "total_hits": 1,
            "total_pages": 1,
            "page": 0,
        },
    )

    assert result == expected
    start.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_playback_awaits_cleanup_and_builds_audio_directive(
    monkeypatch,
):
    envelope = AttrDict({
        "context": {
            "System": {
                "user": {"userId": "test-user"},
                "device": {"deviceId": "test-device"},
            },
        },
        "request": {"type": "IntentRequest"},
    })
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {"playbackSpeed": 1.0, "lastOffsetMs": 0},
        "_dirty": False,
    }
    handler_input = HandlerInput(
        envelope,
        attributes,
        None,
        ResponseBuilder(),
    )
    cancel = AsyncMock()
    monkeypatch.setattr(
        "src.services.playback.start.cancel_feedback_reminder",
        cancel,
    )

    response = await start_playback(
        handler_input,
        {
            "contentId": "content-1",
            "title": "20260514092830_7ac22a7f",
            "spokenTitle": "A readable morning update",
            "creator": "Shetland Life",
            "category": {
                "slug": "monthly-update",
                "name": "Monthly Update",
            },
            "audioUrl": "https://cdn.hear.media/audio/content-1.mp3",
            "playbackSpeeds": [],
        },
        "Now playing.",
    )

    directive = response["directives"][0]
    assert directive["type"] == "AudioPlayer.Play"
    assert directive["audioItem"]["stream"]["url"].startswith("https://")
    assert directive["audioItem"]["stream"]["token"]
    assert directive["audioItem"]["metadata"]["title"] == "A readable morning update"
    assert directive["audioItem"]["metadata"]["subtitle"] == "Monthly Update"
    assert response["shouldEndSession"] is True
    cancel.assert_awaited_once_with(handler_input)
    assert directive["audioItem"]["stream"]["token"] == "content-1"
