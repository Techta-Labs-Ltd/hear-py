from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import httpx
import pytest

from src.alexa.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.clients.hear import HearApiClient, HearApiOptions, HearApiSupport
from src.clients.pool import CircuitHttpClient, HttpCircuitBreaker, HttpCircuitOpen
from src.container import ApplicationContainer
from src.models.playback import Playback
from src.models.search import Search


@pytest.mark.asyncio
async def test_http_circuit_opens_after_repeated_server_failures():
    calls = 0

    async def respond(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    raw = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    client = CircuitHttpClient(raw, HttpCircuitBreaker(2, 60000))
    assert (await client.get("https://service.test/one")).status_code == 503
    assert (await client.get("https://service.test/two")).status_code == 503
    with pytest.raises(HttpCircuitOpen):
        await client.get("https://service.test/three")
    assert calls == 2
    await client.aclose()


def test_search_path_applies_configured_prefix_once():
    client = HearApiClient(HearApiOptions(path_prefix="alexa"))
    assert client._build_api_path(client._build_alexa_search_path()) == "/alexa/search"


def test_search_path_uses_legacy_alexa_route_without_prefix():
    client = HearApiClient(HearApiOptions(path_prefix=""))
    assert client._build_api_path(client._build_alexa_search_path()) == "/alexa/search"


def test_location_path_applies_configured_prefix_once():
    client = HearApiClient(HearApiOptions(path_prefix="alexa"))
    assert (
        client._build_api_path(client._build_alexa_relative_path("location")) == "/alexa/location"
    )


def test_availability_path_applies_configured_prefix_once():
    client = HearApiClient(HearApiOptions(path_prefix="alexa"))
    assert client._build_api_path(client._build_alexa_availability_path()) == "/alexa/availability"


@pytest.mark.asyncio
async def test_availability_sends_bridge_contract_and_normalizes_response(monkeypatch, caplog):
    captured = {}

    async def fake_request(self, method, path, body, timeout_ms):
        captured.update({"method": method, "path": path, "body": body})
        return (
            200,
            {
                "page": 0,
                "limit": 3,
                "total": 2,
                "totalPages": 1,
                "remaining": 0,
                "hasMore": False,
                "nextPage": None,
                "publicationCount": 1,
                "standaloneTrackCount": 7,
                "organizations": [{"id": "org-1", "name": "Redcar Talking Newspaper"}],
                "creators": [{"id": "creator-1", "name": "A Reader"}],
                "publications": [
                    {
                        "publicationId": "publication-1",
                        "title": "Redcar News",
                        "trackCount": 4,
                        "publishedAt": 1788393600,
                        "updatedAt": 1788393600,
                    }
                ],
            },
        )

    monkeypatch.setattr(HearApiClient, "_raw_request", fake_request)
    with caplog.at_level(logging.INFO, logger="src.clients.hear"):
        result = await HearApiClient().availability(
            {
                "filter": {
                    "location": {
                        "city": "Swindon",
                        "countryCode": "gb",
                        "latitude": 51.56,
                        "longitude": -1.78,
                    }
                },
                "page": 0,
                "limit": 3,
            }
        )

    assert captured == {
        "method": "POST",
        "path": "/availability",
        "body": {
            "filter": {
                "location": {
                    "city": "Swindon",
                    "countryCode": "gb",
                    "latitude": 51.56,
                    "longitude": -1.78,
                }
            },
            "page": 0,
            "limit": 3,
        },
    }
    assert result["failed"] is False
    assert result["publication_count"] == 1
    assert result["standalone_track_count"] == 7
    assert result["organizations"] == [
        {"type": "organization", "id": "org-1", "name": "Redcar Talking Newspaper"}
    ]
    assert result["publications"][0]["id"] == "publication-1"
    assert "'city': 'Swindon'" in caplog.text
    assert "'countryCode': 'gb'" in caplog.text
    assert "'latitude': 51.56" in caplog.text
    assert "'longitude': -1.78" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "availability_filter",
    [
        {},
        {"creatorId": "creator-1", "organizationId": "org-1"},
        {"creatorIds": ["creator-1"]},
        {"location": {"city": "Swindon"}, "creatorId": "creator-1"},
        {"location": {"city": "Swindon", "tags": ["news"]}},
    ],
)
async def test_availability_rejects_non_exclusive_filters_without_an_http_call(
    monkeypatch, availability_filter
):
    request = AsyncMock()
    monkeypatch.setattr(HearApiClient, "_raw_request", request)

    result = await HearApiClient().availability({"filter": availability_filter})

    request.assert_not_awaited()
    assert result["failed"] is True
    assert result["_availability_payload"]["filter"] == {}


@pytest.mark.asyncio
async def test_search_omits_sort_values_the_api_rejects(monkeypatch):
    sent = {}

    async def fake_request(self, method, path, body, timeout_ms):
        sent.update(body)
        return (200, {"results": [], "total": 0})

    monkeypatch.setattr(HearApiClient, "_raw_request", fake_request)
    client = HearApiClient()
    await client.search({"query": "news", "sort": "relevance"})
    assert "sort" not in sent
    await client.search({"query": "news", "sort": "recommended"})
    assert sent["sort"] == "recommended"


@pytest.mark.asyncio
async def test_search_serializes_an_absent_query_as_an_empty_string(monkeypatch):
    sent = {}

    async def fake_request(self, method, path, body, timeout_ms):
        sent.update(body)
        return (200, {"results": [], "total": 0})

    monkeypatch.setattr(HearApiClient, "_raw_request", fake_request)
    client = HearApiClient()
    await client.search({"query": None})
    assert sent["query"] == ""
    await client.search({"query": None, "q": "TNF"})
    assert sent["query"] == "TNF"


@pytest.mark.asyncio
async def test_search_sends_and_returns_effective_pagination(monkeypatch):
    sent = {}

    async def fake_request(self, method, path, body, timeout_ms):
        sent.update(body)
        return (200, {"results": [], "total": 0, "page": 0, "limit": 3})

    monkeypatch.setattr(HearApiClient, "_raw_request", fake_request)
    result = await HearApiClient(HearApiOptions(page_limit=3)).search({"query": "TNF"})

    assert sent["limit"] == 3
    assert sent["page"] == 0
    assert result["_search_payload"]["limit"] == 3
    assert result["_search_payload"]["page"] == 0


@pytest.mark.asyncio
async def test_search_forwards_canonical_listener_id(monkeypatch):
    sent = {}

    async def fake_request(self, method, path, body, timeout_ms):
        sent.update(body)
        return (200, {"results": [], "total": 0})

    monkeypatch.setattr(HearApiClient, "_raw_request", fake_request)
    await HearApiClient().search(
        {"query": "news", "listenerId": "listener-1", "alexaUserId": "alexa-1"}
    )
    assert sent["listenerId"] == "listener-1"
    assert sent["alexaUserId"] == "alexa-1"


@pytest.mark.asyncio
async def test_identity_resolution_uses_dedicated_endpoint(monkeypatch):
    captured = {}

    async def fake_request(self, method, path, body, timeout_ms):
        captured.update({"method": method, "path": path, "body": body})
        return (200, {"listenerId": "listener-1"})

    monkeypatch.setattr(HearApiClient, "_raw_request", fake_request)
    result = await HearApiClient(HearApiOptions(path_prefix="alexa")).resolve_listener_identity(
        {"alexaUserId": "alexa-1"},
        timeout_ms=500,
    )

    assert result == {"listenerId": "listener-1"}
    assert captured["method"] == "POST"
    assert captured["path"] == "/listeners/resolve"
    assert captured["body"] == {"alexaUserId": "alexa-1"}


@pytest.mark.asyncio
async def test_search_normalizes_legacy_top_level_dates_into_filter(monkeypatch):
    sent = {}

    async def fake_request(self, method, path, body, timeout_ms):
        sent.update(body)
        return (200, {"results": [], "total": 0})

    monkeypatch.setattr(HearApiClient, "_raw_request", fake_request)
    await HearApiClient().search(
        {
            "query": "",
            "publishedFrom": 1780272000,
            "publishedTo": 1782864000,
            "sort": "latest",
        }
    )
    assert sent["filter"] == {"publishedFrom": 1780272000, "publishedTo": 1782864000}
    assert "publishedFrom" not in sent
    assert "publishedTo" not in sent


def test_allowed_sort_values_match_api_enum():
    assert HearApiSupport.ALLOWED_SORT_VALUES == {
        "recommended",
        "nearest",
        "popular",
        "latest",
        "trending",
    }


@pytest.mark.asyncio
async def test_real_search_shape_reaches_playback_without_catalog_call_error(
    monkeypatch, mock_handler_input
):
    expected = {"response": "play"}
    start = AsyncMock(return_value=expected)
    monkeypatch.setattr("src.models.playback.Playback.start", start)
    result = await Search.auto_play_first_from_search(
        mock_handler_input,
        {
            "results": [
                {
                    "contentId": "content-1",
                    "title": "Morning update",
                    "spokenTitle": "Morning update",
                    "creator": "Shetland Life",
                    "audioUrl": "https://cdn.hear.media/audio/content-1.mp3",
                    "playbackSpeeds": [],
                }
            ],
            "total_hits": 1,
            "total_pages": 1,
            "page": 0,
        },
        deps=ApplicationContainer(),
    )
    assert result == expected
    start.assert_awaited_once()


@pytest.mark.asyncio
async def test_broad_search_playback_intro_uses_request_not_first_item_metadata(
    monkeypatch, mock_handler_input
):
    start = AsyncMock(return_value={"response": "play"})
    monkeypatch.setattr("src.models.playback.Playback.start", start)

    await Search.auto_play_first_from_search(
        mock_handler_input,
        {
            "results": [
                {
                    "contentId": "content-1",
                    "title": "Oxfordshire County Council changes bus ticket pricing",
                    "creator": "Wallingford and District Talking Newspaper",
                    "shortDescription": "A detailed council transport update",
                    "audioUrl": "https://cdn.hear.media/audio/content-1.mp3",
                }
            ],
            "total_hits": 37,
            "_request_label": "content on local transport in Herne Bay",
            "_search_payload": {
                "query": "local transport",
                "filter": {"city": "Herne Bay", "tags": ["local-transport"]},
            },
        },
        deps=ApplicationContainer(),
    )

    assert (
        start.await_args.args[2]
        == "Here are 37 stories about local transport in Herne Bay. Here's the first one."
    )


@pytest.mark.asyncio
async def test_broad_search_fallback_does_not_announce_later_item_source(
    monkeypatch, mock_handler_input
):
    start = AsyncMock(return_value={"response": "play"})
    monkeypatch.setattr("src.models.playback.Playback.start", start)

    result = await Search.auto_play_first_from_search(
        mock_handler_input,
        {
            "results": [
                {"contentId": "unavailable", "title": "Unavailable story"},
                {
                    "contentId": "content-2",
                    "title": "Second result title",
                    "creator": "A single publisher",
                    "audioUrl": "https://cdn.hear.media/audio/content-2.mp3",
                },
            ],
            "total_hits": 12,
            "_request_label": "content on local history",
            "_search_payload": {"query": "local history", "filter": {}},
        },
        deps=ApplicationContainer(),
    )

    assert result == {"response": "play"}
    assert start.await_args.args[2] == (
        "Here are 12 stories about local history. Here's the first one."
    )


@pytest.mark.asyncio
async def test_search_initializes_playback_queue_with_first_page_only(
    monkeypatch, mock_handler_input
):
    start = AsyncMock(return_value={"response": "play"})
    monkeypatch.setattr("src.models.playback.Playback.start", start)
    hear_client = AsyncMock()
    await Search.auto_play_first_from_search(
        mock_handler_input,
        {
            "results": [
                {
                    "contentId": "content-1",
                    "title": "First story",
                    "audioUrl": "https://cdn.hear.media/audio/content-1.mp3",
                },
                {"contentId": "content-2"},
            ],
            "total_hits": 4,
            "total_pages": 3,
            "page": 0,
            "_search_payload": {"query": "wakefield", "page": 0, "limit": 2},
        },
        deps=ApplicationContainer(heara=hear_client),
    )
    store = mock_handler_input.attributes_manager.request_attributes["_store"]
    assert store["playbackQueue"]["orderedContentIds"] == ["content-1", "content-2"]
    assert store["playbackQueue"]["pagination"]["currentPage"] == 0
    assert store["playbackQueue"]["pagination"]["totalPages"] == 3
    hear_client.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_latest_search_initializes_lazy_navigation_queue(monkeypatch, mock_handler_input):
    start = AsyncMock(return_value={"response": "play"})
    monkeypatch.setattr("src.models.playback.Playback.start", start)
    hear_client = AsyncMock()
    first_page = [
        {
            "id": f"content-{index}",
            "contentId": f"content-{index}",
            "title": "Latest Pendle recording" if index == 1 else f"Pendle recording {index}",
            "audioUrl": f"https://cdn.hear.media/audio/content-{index}.mp3",
        }
        for index in range(1, 4)
    ]
    await Search._play_first_search_result(
        mock_handler_input,
        {
            "results": first_page,
            "total_hits": 9,
            "total_pages": 3,
            "page": 0,
            "_search_payload": {"query": "", "page": 0, "limit": 3},
        },
        label="Pendle Voice",
        deps=ApplicationContainer(heara=hear_client),
    )
    store = mock_handler_input.attributes_manager.request_attributes["_store"]
    assert store["playbackQueue"]["orderedContentIds"] == [
        f"content-{index}" for index in range(1, 4)
    ]
    assert [item["contentId"] for item in store["browseCatalog"]["items"]] == [
        "content-1",
        "content-2",
        "content-3",
    ]
    assert store["playbackQueue"]["pagination"]["totalPages"] == 3
    hear_client.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_playback_awaits_cleanup_and_builds_audio_directive(monkeypatch):
    envelope = AttrDict(
        {
            "context": {
                "System": {
                    "user": {"userId": "test-user"},
                    "device": {"deviceId": "test-device"},
                }
            },
            "request": {"type": "IntentRequest"},
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {"playbackSpeed": 1.0, "lastOffsetMs": 0},
        "_dirty": False,
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())
    reminders = AsyncMock()
    response = await Playback.start_playback(
        handler_input,
        {
            "contentId": "content-1",
            "title": "20260514092830_7ac22a7f",
            "spokenTitle": "A readable morning update",
            "creator": "Shetland Life",
            "category": {"slug": "monthly-update", "name": "Monthly Update"},
            "audioUrl": "https://cdn.hear.media/audio/content-1.mp3",
            "playbackSpeeds": [],
        },
        "Now playing.",
        reminders=reminders,
    )
    directive = response["directives"][0]
    assert directive["type"] == "AudioPlayer.Play"
    assert directive["audioItem"]["stream"]["url"].startswith("https://")
    assert directive["audioItem"]["stream"]["token"]
    assert directive["audioItem"]["metadata"]["title"] == "A readable morning update"
    assert directive["audioItem"]["metadata"]["subtitle"] == "Monthly Update"
    assert response["shouldEndSession"] is True
    reminders.cancel.assert_awaited_once_with(handler_input)
    assert directive["audioItem"]["stream"]["token"] == "content-1"
