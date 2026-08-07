from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.handlers.search import auto_play_first_from_search

from src.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.clients.hear import (
    ALLOWED_SORT_VALUES,
    _build_alexa_relative_path,
    _build_alexa_search_path,
    _build_api_path,
    search,
)

from src.services.playback import start_playback



def test_search_path_applies_configured_prefix_once(monkeypatch):
    monkeypatch.setattr(
        "src.clients.hear.settings.HEAR_API_PATH_PREFIX",
        "alexa",
    )

    assert _build_api_path(_build_alexa_search_path()) == "/alexa/search"


def test_search_path_uses_legacy_alexa_route_without_prefix(monkeypatch):
    monkeypatch.setattr(
        "src.clients.hear.settings.HEAR_API_PATH_PREFIX",
        "",
    )

    assert _build_api_path(_build_alexa_search_path()) == "/alexa/search"


def test_location_path_applies_configured_prefix_once(monkeypatch):
    monkeypatch.setattr(
        "src.clients.hear.settings.HEAR_API_PATH_PREFIX",
        "alexa",
    )

    assert _build_api_path(_build_alexa_relative_path("location")) == "/alexa/location"


@pytest.mark.asyncio
async def test_search_omits_sort_values_the_api_rejects(monkeypatch):
    sent = {}

    async def fake_request(method, path, body, timeout_ms):
        sent.update(body)
        return 200, {"results": [], "total": 0}

    monkeypatch.setattr("src.clients.hear._request", fake_request)

    await search({"query": "news", "sort": "relevance"})
    assert "sort" not in sent

    await search({"query": "news", "sort": "recommended"})
    assert sent["sort"] == "recommended"


@pytest.mark.asyncio
async def test_search_serializes_an_absent_query_as_an_empty_string(monkeypatch):
    sent = {}

    async def fake_request(method, path, body, timeout_ms):
        sent.update(body)
        return 200, {"results": [], "total": 0}

    monkeypatch.setattr("src.clients.hear._request", fake_request)

    await search({"query": None})
    assert sent["query"] == ""

    await search({"query": None, "q": "TNF"})
    assert sent["query"] == "TNF"


@pytest.mark.asyncio
async def test_search_normalizes_legacy_top_level_dates_into_filter(monkeypatch):
    sent = {}

    async def fake_request(method, path, body, timeout_ms):
        sent.update(body)
        return 200, {"results": [], "total": 0}

    monkeypatch.setattr("src.clients.hear._request", fake_request)

    await search({
        "query": "",
        "publishedFrom": 1780272000,
        "publishedTo": 1782864000,
        "sort": "latest",
    })

    assert sent["filter"] == {
        "publishedFrom": 1780272000,
        "publishedTo": 1782864000,
    }
    assert "publishedFrom" not in sent
    assert "publishedTo" not in sent


def test_allowed_sort_values_match_api_enum():
    assert ALLOWED_SORT_VALUES == {
        "recommended", "nearest", "popular", "latest", "trending",
    }


@pytest.mark.asyncio
async def test_real_search_shape_reaches_playback_without_catalog_call_error(
    monkeypatch,
    mock_handler_input,
):
    expected = {"response": "play"}
    start = AsyncMock(return_value=expected)
    monkeypatch.setattr("src.handlers.search.start_playback", start)
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
        "src.services.playback.cancel_feedback_reminder",
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
