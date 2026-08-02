from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.adapters.memory_persistence import MemoryPersistenceAdapter
from src.application import build_skill


USER_ID = "amzn1.ask.account.AUDIO_RUNTIME_TEST"
APPLICATION_ID = "amzn1.ask.skill.test"
CONTENT_ID = "11111111-1111-1111-1111-111111111111"


def _event(request: dict, *, new: bool = False) -> dict:
    return {
        "version": "1.0",
        "session": {
            "new": new,
            "sessionId": "audio-runtime-session",
            "application": {"applicationId": APPLICATION_ID},
            "attributes": {},
            "user": {"userId": USER_ID},
        },
        "context": {
            "System": {
                "application": {"applicationId": APPLICATION_ID},
                "user": {"userId": USER_ID, "permissions": {"scopes": {}}},
                "device": {
                    "deviceId": "audio-runtime-device",
                    "supportedInterfaces": {"AudioPlayer": {}},
                },
                "apiEndpoint": "https://api.eu.amazonalexa.com",
                "apiAccessToken": "test-token",
            },
            "AudioPlayer": {"playerActivity": "IDLE"},
        },
        "request": {
            "requestId": "audio-runtime-request",
            "timestamp": "2026-07-29T12:00:00Z",
            "locale": "en-GB",
            **request,
        },
    }


def _playback_state(*, status: str = "paused", offset_ms: int = 42_000) -> dict:
    return {
        "contentId": CONTENT_ID,
        "token": CONTENT_ID,
        "title": "Sheffield monthly bulletin",
        "creatorId": "creator-1",
        "creatorName": "Sheffield Talking Newspaper",
        "audioUrl": "https://cdn.hear.media/audio/monthly-bulletin.mp3",
        "durationMs": 180_000,
        "offsetMs": offset_ms,
        "listenedMs": offset_ms,
        "sessionId": f"{CONTENT_ID}:session",
        "status": status,
        "startedAt": 1,
        "updatedAt": 1,
    }


@pytest.mark.asyncio
async def test_resume_yes_uses_persisted_playable_state_without_search(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "awaitingResume": True,
        "activePlayback": _playback_state(),
    }
    search = AsyncMock()
    monkeypatch.setattr("src.handlers.intents.system.search", search)

    result = await build_skill(persistence).invoke(
        _event({
            "type": "IntentRequest",
            "intent": {"name": "AMAZON.YesIntent", "slots": {}},
        }),
        None,
    )

    search.assert_not_awaited()
    response = result["response"]
    directive = response["directives"][0]
    assert directive["type"] == "AudioPlayer.Play"
    assert directive["audioItem"]["stream"]["token"] == CONTENT_ID
    assert directive["audioItem"]["stream"]["offsetInMilliseconds"] == 42_000
    assert "Continuing where you stopped" in response["outputSpeech"]["ssml"]
    assert response["shouldEndSession"] is True


@pytest.mark.asyncio
async def test_resume_no_abandons_playback_and_offers_next_listening_options():
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "awaitingResume": True,
        "activePlayback": _playback_state(),
    }

    result = await build_skill(persistence).invoke(
        _event({
            "type": "IntentRequest",
            "intent": {"name": "AMAZON.NoIntent", "slots": {}},
        }),
        None,
    )

    response = result["response"]
    state = persistence._store[USER_ID]
    assert state["activePlayback"]["status"] == "abandoned"
    assert state["awaitingResume"] is False
    assert state["activeDialog"] is None
    assert response["shouldEndSession"] is False
    assert "Okay, I won't continue that recording." in response["outputSpeech"]["ssml"]
    assert "news or sport" in response["outputSpeech"]["ssml"]
    assert "talking newspaper" in response["reprompt"]["outputSpeech"]["ssml"]
    assert "what's trending" in response["reprompt"]["outputSpeech"]["ssml"]


@pytest.mark.asyncio
async def test_resume_no_does_not_activate_incomplete_feedback_candidate():
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "awaitingResume": True,
        "activePlayback": _playback_state(offset_ms=120_000),
        "feedbackCandidates": [{
            "feedbackKey": CONTENT_ID,
            "contentId": CONTENT_ID,
            "listenedMs": 120_000,
            "completed": False,
            "sessionId": f"{CONTENT_ID}:session",
        }],
    }

    await build_skill(persistence).invoke(
        _event({
            "type": "IntentRequest",
            "intent": {"name": "AMAZON.NoIntent", "slots": {}},
        }),
        None,
    )

    state = persistence._store[USER_ID]
    assert state.get("awaitingFeedback") is not True
    assert state.get("pendingFeedback") is None


@pytest.mark.asyncio
async def test_playback_started_accepts_raw_camel_case_offset(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="starting", offset_ms=0),
    }
    monkeypatch.setattr(
        "src.handlers.audio.playback_started.consume_notification_for_playback",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "src.handlers.audio.playback_started.emit_listening_event",
        AsyncMock(),
    )

    await build_skill(persistence).invoke(
        _event({
            "type": "AudioPlayer.PlaybackStarted",
            "token": CONTENT_ID,
            "offsetInMilliseconds": 12_345,
        }),
        None,
    )

    state = persistence._store[USER_ID]["activePlayback"]
    assert state["status"] == "playing"
    assert state["offsetMs"] == 12_345
    assert state["listenedMs"] == 12_345


@pytest.mark.parametrize("event_type", [
    "AudioPlayer.PlaybackProgressReportDelayPassed",
    "AudioPlayer.PlaybackProgressReportIntervalPassed",
])
@pytest.mark.asyncio
async def test_playback_progress_events_persist_and_sync(
    monkeypatch,
    event_type,
):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=12_345),
    }
    emit = AsyncMock()
    monkeypatch.setattr(
        "src.handlers.audio.playback_progress_report.emit_listening_event",
        emit,
    )

    await build_skill(persistence).invoke(
        _event({
            "type": event_type,
            "token": CONTENT_ID,
            "offsetInMilliseconds": 91_000,
        }),
        None,
    )

    state = persistence._store[USER_ID]["activePlayback"]
    assert state["offsetMs"] == 91_000
    assert state["listenedMs"] == 91_000
    emit.assert_awaited_once()
    assert emit.await_args.args[1] == "progress"


@pytest.mark.asyncio
async def test_playback_stopped_never_creates_feedback_candidate(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=120_000),
    }
    monkeypatch.setattr(
        "src.handlers.audio.playback_stopped.emit_listening_event",
        AsyncMock(),
    )

    await build_skill(persistence).invoke(
        _event({
            "type": "AudioPlayer.PlaybackStopped",
            "token": CONTENT_ID,
            "offsetInMilliseconds": 120_000,
        }),
        None,
    )

    state = persistence._store[USER_ID]
    assert state["activePlayback"]["status"] == "paused"
    assert state.get("feedbackCandidates") in (None, [])


@pytest.mark.asyncio
async def test_playback_nearly_finished_syncs_without_a_queue(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=170_000),
    }
    emit = AsyncMock()
    monkeypatch.setattr(
        "src.handlers.audio.playback_nearly_finished.emit_listening_event",
        emit,
    )

    await build_skill(persistence).invoke(
        _event({
            "type": "AudioPlayer.PlaybackNearlyFinished",
            "token": CONTENT_ID,
            "offsetInMilliseconds": 170_000,
        }),
        None,
    )

    emit.assert_awaited_once()
    assert emit.await_args.args[1] == "nearly_finished"


@pytest.mark.asyncio
async def test_playback_finished_accepts_raw_camel_case_offset(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=12_345),
    }
    monkeypatch.setattr(
        "src.handlers.audio.playback_finished.emit_listening_event",
        AsyncMock(),
    )

    await build_skill(persistence).invoke(
        _event({
            "type": "AudioPlayer.PlaybackFinished",
            "token": CONTENT_ID,
            "offsetInMilliseconds": 179_500,
        }),
        None,
    )

    state = persistence._store[USER_ID]["activePlayback"]
    assert state["status"] == "completed"
    assert state["offsetMs"] == 180_000
    assert state["listenedMs"] == 180_000
    pending = persistence._store[USER_ID]["pendingFeedback"]
    assert pending["feedbackKey"] == CONTENT_ID
    assert pending["completed"] is True
