from unittest.mock import AsyncMock, MagicMock

import pytest

from src.alexa.context import RequestContext
from src.alexa.social import FollowCreator, UnfollowCreator
from src.constants.state import StateSchema
from src.models.user import User


def _bind_session(handler_input, session: dict) -> None:
    handler_input.attributes_manager.get_session_attributes = lambda: session

    def set_session(value: dict) -> None:
        session.clear()
        session.update(value)

    handler_input.attributes_manager.set_session_attributes = set_session


def _reset_store(handler_input) -> None:
    handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "listenerId": "listener-1",
        "lastCompletedSource": {
            "organizationId": "org-1",
            "organizationName": "Longeaton and District Talking Newspaper",
        },
    }


@pytest.mark.asyncio
async def test_repeated_follow_uses_session_projection_but_emits_only_one_event(
    mock_handler_input,
):
    session = {}
    _bind_session(mock_handler_input, session)
    _reset_store(mock_handler_input)
    events = MagicMock()
    feedback = MagicMock()
    feedback.clear = AsyncMock()
    play_followed = AsyncMock()

    follow = FollowCreator(User(), feedback, events, play_followed)
    request = RequestContext.bind(mock_handler_input)

    await follow.execute(request)
    assert events.following.call_count == 1
    assert events.following.call_args.kwargs["followed"] is True
    assert session["followedCreators"] == [
        {
            "id": "org-1",
            "name": "Longeaton and District Talking Newspaper",
            "type": "organization",
        }
    ]

    _reset_store(mock_handler_input)
    mock_handler_input.response_builder.speak.reset_mock()
    await follow.execute(request)

    assert events.following.call_count == 1
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "already following" in spoken.lower()
    play_followed.assert_not_awaited()


@pytest.mark.asyncio
async def test_unfollow_emits_event_when_session_has_no_known_follow_projection(
    mock_handler_input,
):
    session = {}
    _bind_session(mock_handler_input, session)
    _reset_store(mock_handler_input)
    events = MagicMock()

    await UnfollowCreator(User(), events).execute(RequestContext.bind(mock_handler_input))

    events.following.assert_called_once()
    payload = events.following.call_args.kwargs
    assert payload["followed"] is False
    assert payload["listener_id"] == "listener-1"
    assert payload["source"] == {
        "type": "organization",
        "id": "org-1",
        "name": "Longeaton and District Talking Newspaper",
    }
    assert session["followedCreators"] == []


@pytest.mark.asyncio
async def test_repeated_unfollow_is_suppressed_by_session_projection(
    mock_handler_input,
):
    session = {
        "followedCreators": [
            {
                "id": "org-1",
                "name": "Longeaton and District Talking Newspaper",
                "type": "organization",
            }
        ]
    }
    _bind_session(mock_handler_input, session)
    _reset_store(mock_handler_input)
    events = MagicMock()
    unfollow = UnfollowCreator(User(), events)
    request = RequestContext.bind(mock_handler_input)

    await unfollow.execute(request)
    assert events.following.call_count == 1
    assert session["followedCreators"] == []

    _reset_store(mock_handler_input)
    mock_handler_input.response_builder.speak.reset_mock()
    await unfollow.execute(request)

    assert events.following.call_count == 1
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "not following" in spoken.lower()
