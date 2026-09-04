from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.models.affirmative import Affirmative
from src.models.playback import Playback
from src.models.playback_state import PlaybackQueue
from src.models.search import Search
from src.models.user import User


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
    assert Search.initial_search_queue_items(result) == result["results"]
    assert Search.search_queue_pagination(result) == {
        "search_payload": {"query": "", "page": 0, "limit": 3},
        "current_page": 0,
        "total_pages": 334,
        "page_limit": 3,
    }


@pytest.mark.asyncio
async def test_next_page_is_loaded_only_when_requested(mock_handler_input):
    first_page = [{"contentId": f"content-{index}"} for index in range(1, 4)]
    PlaybackQueue(User()).initialize(
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
    loaded = await PlaybackQueue(User()).load_next_page(mock_handler_input, client)
    assert loaded is True
    client.search.assert_awaited_once()
    assert client.search.await_args.args[0]["page"] == 1
    assert client.search.await_args.args[0]["limit"] == 3
    queue = PlaybackQueue.read(User.snapshot(mock_handler_input))
    assert queue["orderedContentIds"] == [
        "content-1",
        "content-2",
        "content-3",
        "content-4",
        "content-5",
        "content-6",
    ]
    assert queue["pagination"]["currentPage"] == 1


@pytest.mark.asyncio
async def test_failed_next_page_keeps_loaded_queue_intact(mock_handler_input):
    PlaybackQueue(User()).initialize(
        mock_handler_input,
        [{"contentId": "content-1"}],
        search_payload={"query": "news", "page": 0, "limit": 1},
        current_page=0,
        total_pages=2,
        page_limit=1,
    )
    client = AsyncMock()
    client.search.return_value = {"results": [], "failed": True}
    assert await PlaybackQueue(User()).load_next_page(mock_handler_input, client) is False
    queue = PlaybackQueue.read(User.snapshot(mock_handler_input))
    assert queue["orderedContentIds"] == ["content-1"]
    assert queue["pagination"]["currentPage"] == 0


@pytest.mark.asyncio
async def test_voice_next_loads_next_page_at_loaded_boundary(monkeypatch, mock_handler_input):
    first_page = [
        {
            "contentId": f"content-{index}",
            "title": f"Story {index}",
            "audioUrl": f"https://cdn.hear.media/{index}.mp3",
        }
        for index in range(1, 4)
    ]
    queues = PlaybackQueue(User())
    queues.initialize(
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
        "results": [
            {
                "contentId": "content-4",
                "title": "Story 4",
                "audioUrl": "https://cdn.hear.media/4.mp3",
            }
        ],
        "page": 1,
        "total_pages": 2,
        "failed": False,
    }
    start = AsyncMock(return_value={"response": "play"})
    playback = type("Playback", (), {"start": staticmethod(start), "queue": queues})()
    result = await Playback.play_queue_delta(
        mock_handler_input,
        1,
        "Playing the next recording.",
        deps=type(
            "Deps",
            (),
            {
                "heara": client,
                "reminders": AsyncMock(),
                "playback": playback,
                "search": Search,
                "user": User(),
            },
        )(),
    )
    assert result == {"response": "play"}
    assert client.search.await_count == 1
    assert client.search.await_args.args[0]["page"] == 1
    start.assert_awaited_once()
    assert start.await_args.args[1]["contentId"] == "content-4"
    queue = PlaybackQueue.read(User.snapshot(mock_handler_input))
    assert queue["currentIndex"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("item", "expected_speech"),
    [
        (
            {"contentId": "content-1"},
            "You've reached the end of these recordings.",
        ),
        (
            {
                "contentId": "content-1",
                "publicationId": "publication-1",
                "publicationTitle": "The Gazette",
            },
            "You've reached the end of this publication.",
        ),
    ],
)
async def test_voice_next_explains_when_the_queue_has_ended(
    mock_handler_input, item, expected_speech
):
    queues = PlaybackQueue(User())
    queues.initialize(mock_handler_input, [item])
    client = AsyncMock()
    playback = type("Playback", (), {"queue": queues})()

    await Playback.play_queue_delta(
        mock_handler_input,
        1,
        "Playing the next recording.",
        deps=type(
            "Deps",
            (),
            {
                "heara": client,
                "playback": playback,
                "user": User(),
            },
        )(),
    )

    client.search.assert_not_awaited()
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert expected_speech in spoken
    assert "no content available" not in spoken


@pytest.mark.asyncio
async def test_voice_next_does_not_claim_queue_ended_when_next_page_failed(
    mock_handler_input,
):
    queues = PlaybackQueue(User())
    queues.initialize(
        mock_handler_input,
        [{"contentId": "content-1"}],
        search_payload={"query": "news", "page": 0, "limit": 1},
        current_page=0,
        total_pages=2,
        page_limit=1,
    )
    client = AsyncMock()
    client.search.return_value = {"results": [], "failed": True}
    playback = type("Playback", (), {"queue": queues})()

    await Playback.play_queue_delta(
        mock_handler_input,
        1,
        "Playing the next recording.",
        deps=type(
            "Deps",
            (),
            {
                "heara": client,
                "playback": playback,
                "user": User(),
            },
        )(),
    )

    client.search.assert_awaited_once()
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "no content available" in spoken
    assert "reached the end" not in spoken


@pytest.mark.asyncio
async def test_still_listening_confirmation_uses_publication_end_message(
    mock_handler_input,
):
    user = User()
    queues = PlaybackQueue(user)
    queues.initialize(
        mock_handler_input,
        [
            {
                "contentId": "content-1",
                "publicationId": "publication-1",
                "publicationTitle": "The Gazette",
            }
        ],
    )
    feedback = type("Feedback", (), {"clear": AsyncMock()})()
    client = AsyncMock()
    playback = type("Playback", (), {"queue": queues})()
    deps = type(
        "Deps",
        (),
        {
            "feedback": feedback,
            "heara": client,
            "playback": playback,
            "user": user,
        },
    )()

    await Affirmative(deps=deps)._handle_still_listening_yes(
        mock_handler_input, user.snapshot(mock_handler_input)
    )

    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "You've reached the end of this publication." in spoken
    assert PlaybackQueue.read(user.snapshot(mock_handler_input)) is None


@pytest.mark.asyncio
async def test_still_listening_page_failure_preserves_queue(mock_handler_input):
    user = User()
    queues = PlaybackQueue(user)
    queues.initialize(
        mock_handler_input,
        [{"contentId": "content-1"}],
        search_payload={"query": "news", "page": 0, "limit": 1},
        current_page=0,
        total_pages=2,
        page_limit=1,
    )
    feedback = type("Feedback", (), {"clear": AsyncMock()})()
    client = AsyncMock()
    client.search.return_value = {"results": [], "failed": True}
    playback = type("Playback", (), {"queue": queues})()
    deps = type(
        "Deps",
        (),
        {
            "feedback": feedback,
            "heara": client,
            "playback": playback,
            "user": user,
        },
    )()

    await Affirmative(deps=deps)._handle_still_listening_yes(
        mock_handler_input, user.snapshot(mock_handler_input)
    )

    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "no content available" in spoken
    assert "reached the end" not in spoken
    assert PlaybackQueue.read(user.snapshot(mock_handler_input)) is not None
