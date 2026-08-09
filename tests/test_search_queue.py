from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.services.queue import init_queue, read_playback_queue
from src.services.search_queue import (
    initial_search_queue_items,
    load_next_search_queue_page,
    search_queue_pagination,
)
from src.services.store import get_store
from src.handlers.playback import _play_queue_delta


def test_initial_search_queue_contains_only_the_loaded_page():
    result = {
        "results": [
            {"contentId": "content-1"},
            {"contentId": "content-2"},
            {"contentId": "content-3"},
        ],
        "page": 0,
        "total_pages": 334,
        "_search_payload": {"query": "", "page": 0, "limit": 3},
    }

    assert initial_search_queue_items(result) == result["results"]
    assert search_queue_pagination(result) == {
        "search_payload": {"query": "", "page": 0, "limit": 3},
        "current_page": 0,
        "total_pages": 334,
        "page_limit": 3,
    }


@pytest.mark.asyncio
async def test_next_page_is_loaded_only_when_requested(mock_handler_input):
    first_page = [{"contentId": f"content-{index}"} for index in range(1, 4)]
    init_queue(
        mock_handler_input,
        first_page,
        search_payload={"query": "news", "page": 0, "limit": 3},
        current_page=0,
        total_pages=3,
        page_limit=3,
    )
    client = AsyncMock()
    client.search.return_value = {
        "results": [
            {
                "contentId": f"content-{index}",
                "title": f"Story {index}",
                "audioUrl": f"https://cdn.hear.media/{index}.mp3",
            }
            for index in range(4, 7)
        ],
        "page": 1,
        "total_pages": 3,
        "failed": False,
    }

    loaded = await load_next_search_queue_page(mock_handler_input, client)

    assert loaded is True
    client.search.assert_awaited_once()
    assert client.search.await_args.args[0]["page"] == 1
    assert client.search.await_args.args[0]["limit"] == 3
    queue = read_playback_queue(get_store(mock_handler_input))
    assert queue["orderedContentIds"] == [
        "content-1", "content-2", "content-3",
        "content-4", "content-5", "content-6",
    ]
    assert queue["pagination"]["currentPage"] == 1


@pytest.mark.asyncio
async def test_failed_next_page_keeps_loaded_queue_intact(mock_handler_input):
    init_queue(
        mock_handler_input,
        [{"contentId": "content-1"}],
        search_payload={"query": "news", "page": 0, "limit": 1},
        current_page=0,
        total_pages=2,
        page_limit=1,
    )
    client = AsyncMock()
    client.search.return_value = {"results": [], "failed": True}

    assert await load_next_search_queue_page(mock_handler_input, client) is False
    queue = read_playback_queue(get_store(mock_handler_input))
    assert queue["orderedContentIds"] == ["content-1"]
    assert queue["pagination"]["currentPage"] == 0


@pytest.mark.asyncio
async def test_voice_next_loads_next_page_at_loaded_boundary(
    monkeypatch,
    mock_handler_input,
):
    first_page = [
        {
            "contentId": f"content-{index}",
            "title": f"Story {index}",
            "audioUrl": f"https://cdn.hear.media/{index}.mp3",
        }
        for index in range(1, 4)
    ]
    init_queue(
        mock_handler_input,
        first_page,
        start_index=2,
        search_payload={"query": "news", "page": 0, "limit": 3},
        current_page=0,
        total_pages=2,
        page_limit=3,
    )
    mock_handler_input.attributes_manager.request_attributes["_store"]["browseCatalog"] = {
        "items": first_page,
        "currentPage": 0,
        "totalPages": 2,
    }
    client = AsyncMock()
    client.search.return_value = {
        "results": [{
            "contentId": "content-4",
            "title": "Story 4",
            "audioUrl": "https://cdn.hear.media/4.mp3",
        }],
        "page": 1,
        "total_pages": 2,
        "failed": False,
    }
    start = AsyncMock(return_value={"response": "play"})
    monkeypatch.setattr("src.handlers.playback.start_playback", start)

    result = await _play_queue_delta(
        mock_handler_input,
        1,
        "Playing the next recording.",
        deps=type("Deps", (), {"heara": client})(),
    )

    assert result == {"response": "play"}
    assert client.search.await_count == 1
    assert client.search.await_args.args[0]["page"] == 1
    start.assert_awaited_once()
    assert start.await_args.args[1]["contentId"] == "content-4"
    queue = read_playback_queue(get_store(mock_handler_input))
    assert queue["currentIndex"] == 3
