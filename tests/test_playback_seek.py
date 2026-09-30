from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.alexa.playback import AlexaPlayback
from src.alexa.playback_controls import PlaybackControls
from src.alexa.runtime import AttrDict
from src.models.user import User


def _intent(handler_input, name: str, slots: dict | None = None):
    envelope = AttrDict(handler_input.request_envelope)
    envelope.context = AttrDict(envelope["context"])
    envelope.context.AudioPlayer = AttrDict(
        {
            "playerActivity": "PLAYING",
            "token": "content-1",
            "offsetInMilliseconds": 120000,
        }
    )
    envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "requestId": "amzn1.echo-api.request.seek",
            "timestamp": "2026-09-30T12:00:00Z",
            "locale": "en-GB",
            "intent": {
                "name": name,
                "confirmationStatus": "NONE",
                "slots": slots or {},
            },
        }
    )
    handler_input.request_envelope = envelope
    return handler_input


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("direction", "intent_name", "expected_offset", "expected_speech"),
    (
        (1, "FastForwardIntent", 135000, "Skipping ahead 15 seconds."),
        (-1, "RewindIntent", 105000, "Going back 15 seconds."),
    ),
)
async def test_seek_uses_live_audio_player_position(
    mock_handler_input,
    direction,
    intent_name,
    expected_offset,
    expected_speech,
):
    handler_input = _intent(mock_handler_input, intent_name)
    stored_state = {
        "contentId": "content-1",
        "token": "content-1",
        "status": "playing",
        "offsetMs": 30000,
        "durationMs": 300000,
        "audioUrl": "https://cdn.hear.media/content-1.mp3",
    }
    state = SimpleNamespace(current=MagicMock(return_value=stored_state))
    playback = SimpleNamespace(
        state=state,
        emit=AsyncMock(return_value=True),
        resume=AsyncMock(return_value={"response": True}),
    )
    controls = PlaybackControls(playback, User(), SimpleNamespace())

    response = await controls.seek(handler_input, direction)

    assert response == {"response": True}
    playback.resume.assert_awaited_once()
    resume_state = playback.resume.await_args.args[1]
    speech = playback.resume.await_args.args[2]
    assert resume_state["offsetMs"] == expected_offset
    assert speech == expected_speech


def test_seek_defaults_are_short_and_directional(mock_handler_input):
    forward = _intent(mock_handler_input, "FastForwardIntent")
    assert AlexaPlayback.resolve_seek_ms(forward, 1) == 15000
    rewind = _intent(mock_handler_input, "RewindIntent")
    assert AlexaPlayback.resolve_seek_ms(rewind, -1) == 15000


@pytest.mark.parametrize(
    ("value", "expected_ms"),
    (
        ("PT15S", 15000),
        ("PT30S", 30000),
        ("PT1M", 60000),
        ("15 seconds", 15000),
        ("30 secs", 30000),
        ("2 minutes", 120000),
        ("1 minute 30 seconds", 90000),
    ),
)
def test_explicit_seek_duration_overrides_default(
    mock_handler_input, value, expected_ms
):
    handler_input = _intent(
        mock_handler_input,
        "FastForwardIntent",
        {"time": {"name": "time", "value": value}},
    )
    assert AlexaPlayback.resolve_seek_ms(handler_input, 1) == expected_ms
