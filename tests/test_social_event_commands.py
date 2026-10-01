from unittest.mock import AsyncMock, MagicMock

import pytest

from src.alexa.context import RequestContext
from src.alexa.following_state import FollowingSessionState
from src.alexa.social import FollowCreator, UnfollowCreator
from src.alexa.speech import Speech
from src.constants.state import StateSchema
from src.models.user import User
from src.services.events import OutboundEventService


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
        "activePlayback": {
            "contentId": "track-1",
            "status": "abandoned",
            "organizationId": "org-1",
            "organizationName": "Longeaton and District Talking Newspaper",
        },
    }


def _events(captured: list[dict], *, accepted: bool = True) -> OutboundEventService:
    def stage(_handler_input, envelope: dict) -> bool:
        captured.append(envelope)
        return accepted

    return OutboundEventService(stage_event=stage)


@pytest.mark.asyncio
async def test_repeated_follow_stages_one_existing_follow_event_per_session(
    mock_handler_input,
):
    session: dict = {}
    captured: list[dict] = []
    _bind_session(mock_handler_input, session)
    _reset_store(mock_handler_input)
    feedback = MagicMock()
    feedback.clear = AsyncMock()
    play_followed = AsyncMock()
    follow = FollowCreator(User(), feedback, _events(captured), play_followed)
    request = RequestContext.bind(mock_handler_input)

    await follow.execute(request)

    assert len(captured) == 1
    assert captured[0]["event"] == "user.followed_organization"
    assert captured[0]["data"]["sourceId"] == "org-1"
    assert FollowingSessionState.status(mock_handler_input, "org-1", "organization") is True

    _reset_store(mock_handler_input)
    mock_handler_input.response_builder.speak.reset_mock()
    await follow.execute(request)

    assert len(captured) == 1
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "already following" in spoken.lower()
    play_followed.assert_not_awaited()


@pytest.mark.asyncio
async def test_unfollow_stages_event_even_when_authoritative_state_is_unknown_locally(
    mock_handler_input,
):
    session: dict = {}
    captured: list[dict] = []
    _bind_session(mock_handler_input, session)
    _reset_store(mock_handler_input)

    await UnfollowCreator(User(), _events(captured)).execute(
        RequestContext.bind(mock_handler_input)
    )

    assert len(captured) == 1
    assert captured[0]["event"] == "user.unfollowed_organization"
    assert captured[0]["data"]["sourceId"] == "org-1"
    assert FollowingSessionState.status(mock_handler_input, "org-1", "organization") is False


@pytest.mark.asyncio
async def test_repeated_unfollow_is_suppressed_only_by_session_command_knowledge(
    mock_handler_input,
):
    session: dict = {}
    captured: list[dict] = []
    _bind_session(mock_handler_input, session)
    _reset_store(mock_handler_input)
    FollowingSessionState.record(
        mock_handler_input,
        source_id="org-1",
        source_type="organization",
        followed=True,
    )
    unfollow = UnfollowCreator(User(), _events(captured))
    request = RequestContext.bind(mock_handler_input)

    await unfollow.execute(request)
    assert len(captured) == 1

    _reset_store(mock_handler_input)
    mock_handler_input.response_builder.speak.reset_mock()
    await unfollow.execute(request)

    assert len(captured) == 1
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "not following" in spoken.lower()


@pytest.mark.asyncio
async def test_failed_follow_event_staging_does_not_record_local_success(
    mock_handler_input,
):
    session: dict = {}
    captured: list[dict] = []
    _bind_session(mock_handler_input, session)
    _reset_store(mock_handler_input)
    feedback = MagicMock()
    feedback.clear = AsyncMock()
    follow = FollowCreator(User(), feedback, _events(captured, accepted=False), AsyncMock())

    await follow.execute(RequestContext.bind(mock_handler_input))

    assert len(captured) == 1
    assert FollowingSessionState.status(mock_handler_input, "org-1", "organization") is None
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert spoken == Speech.ERROR_GENERIC


@pytest.mark.asyncio
async def test_enjoyed_feedback_does_not_reoffer_follow_after_session_follow(
    mock_handler_input,
):
    from src.alexa.feedback_response import EnjoyedFeedback

    session: dict = {}
    _bind_session(mock_handler_input, session)
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "awaitingFeedback": True,
        "pendingFeedback": {
            "contentId": "track-1",
            "title": "Local news",
            "organizationId": "org-1",
            "organizationName": "Longeaton and District Talking Newspaper",
        },
    }
    FollowingSessionState.record(
        mock_handler_input,
        source_id="org-1",
        source_type="organization",
        followed=True,
    )
    feedback = MagicMock()
    feedback.submit = AsyncMock()
    feedback.clear = AsyncMock()

    await EnjoyedFeedback(
        feedback,
        MagicMock(),
        User(),
        notifications=None,
    ).execute(RequestContext.bind(mock_handler_input))

    store = User.snapshot(mock_handler_input)
    assert store["awaitingFollow"] is False
    assert store["pendingFollowSource"] is None
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "follow" not in spoken.lower()
