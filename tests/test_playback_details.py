from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.alexa.playback_details import PlaybackDetails
from src.models.user import User


def _active_playback(**overrides) -> dict:
    state = {
        "contentId": "track-1",
        "title": "Local history",
        "creatorName": "Jane Smith",
        "organizationName": "Blackpool Gazette",
        "summary": "A look at Blackpool's historic promenade.",
        "audioUrl": "https://audio.example.test/track-1.mp3",
        "status": "playing",
        "offsetMs": 45000,
    }
    return {**state, **overrides}


def _details() -> tuple[PlaybackDetails, MagicMock]:
    controls = MagicMock()
    controls.pause_active = AsyncMock(return_value={"type": "AudioPlayer.Stop"})
    return PlaybackDetails(User(), controls), controls


@pytest.mark.asyncio
async def test_publication_about_uses_active_organization_not_summary(mock_handler_input):
    details, controls = _details()
    User.update(
        mock_handler_input,
        {
            "currentSummary": "Stale summary that must not be spoken.",
            "activePlayback": _active_playback(
                publicationId="publication-1",
                publicationTitle="Weekly Gazette",
                subjectType="publication",
                summary="A track summary that must not be spoken.",
            ),
        },
    )

    await details.about(mock_handler_input)

    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    store = User.snapshot(mock_handler_input)
    assert "This content is from Blackpool Gazette." in spoken
    assert "track summary" not in spoken
    assert "Stale summary" not in spoken
    assert "Weekly Gazette" in spoken
    assert store["activeDialog"]["type"] == "resume"
    assert store["awaitingResume"] is True
    controls.pause_active.assert_awaited_once_with(mock_handler_input)


@pytest.mark.asyncio
async def test_creator_uses_active_playback_not_legacy_credit(mock_handler_input):
    details, controls = _details()
    User.update(
        mock_handler_input,
        {
            "currentContentTitle": "Stale title",
            "currentCreator": "Stale creator",
            "activePlayback": _active_playback(),
        },
    )

    await details.creator(mock_handler_input)

    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "Local history, created by Jane Smith." in spoken
    assert "Stale" not in spoken
    controls.pause_active.assert_awaited_once_with(mock_handler_input)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "failed", "abandoned"])
async def test_finished_playback_cannot_be_described(mock_handler_input, status):
    details, controls = _details()
    User.update(mock_handler_input, {"activePlayback": _active_playback(status=status)})

    await details.about(mock_handler_input)

    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert PlaybackDetails.NO_ACTIVE_CONTENT in spoken
    controls.pause_active.assert_not_awaited()


@pytest.mark.asyncio
async def test_feedback_prompt_is_restored_without_replacing_its_dialog(
    mock_handler_input,
):
    details, controls = _details()
    pending = {"contentId": "track-1", "title": "Local history"}
    User.update(
        mock_handler_input,
        {
            "activePlayback": _active_playback(status="paused"),
            "awaitingFeedback": True,
            "pendingFeedback": pending,
            "activeDialog": {"type": "feedback", "context": pending},
        },
    )

    await details.creator(mock_handler_input)

    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    store = User.snapshot(mock_handler_input)
    assert "created by Jane Smith" in spoken
    assert "Did you enjoy Local history?" in spoken
    assert store["activeDialog"]["type"] == "feedback"
    assert store["awaitingFeedback"] is True
    controls.pause_active.assert_not_awaited()


@pytest.mark.asyncio
async def test_publication_continuation_prompt_is_restored(mock_handler_input):
    details, controls = _details()
    context = {"kind": "publication", "name": "Weekly Gazette"}
    User.update(
        mock_handler_input,
        {
            "activePlayback": _active_playback(
                status="paused",
                publicationId="publication-1",
                publicationTitle="Weekly Gazette",
                subjectType="publication",
            ),
            "awaitingFeedbackContinuation": True,
            "feedbackContinuation": context,
            "activeDialog": {"type": "feedback_continuation", "context": context},
        },
    )

    await details.about(mock_handler_input)

    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    store = User.snapshot(mock_handler_input)
    assert "This content is from Blackpool Gazette." in spoken
    assert "Would you like to continue listening to Weekly Gazette?" in spoken
    assert store["activeDialog"]["type"] == "feedback_continuation"
    assert store["awaitingFeedbackContinuation"] is True
    controls.pause_active.assert_not_awaited()
