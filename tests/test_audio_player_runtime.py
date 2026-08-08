from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.adapters.memory_persistence import MemoryPersistenceAdapter
from src.application import build_skill
from src.clients.hear import HearApiClient


USER_ID = "amzn1.ask.account.AUDIO_RUNTIME_TEST"
APPLICATION_ID = "amzn1.ask.skill.test"
CONTENT_ID = "11111111-1111-1111-1111-111111111111"
SECOND_CONTENT_ID = "22222222-2222-2222-2222-222222222222"
THIRD_CONTENT_ID = "33333333-3333-3333-3333-333333333333"


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


def _queued_content(content_id: str, title: str) -> dict:
    return {
        "contentId": content_id,
        "title": title,
        "spokenTitle": title,
        "creatorId": "creator-1",
        "creatorName": "Sheffield Talking Newspaper",
        "audioUrl": f"https://cdn.hear.media/audio/{content_id}.mp3",
        "durationMs": 180_000,
        "playbackSpeeds": [],
    }


def _fake_search(catalog: list[dict]) -> AsyncMock:
    async def _search(payload):
        wanted = (payload.get("filter") or {}).get("contentIds") or []
        wanted = [str(value) for value in wanted]
        return {
            "results": [item for item in catalog if item["contentId"] in wanted],
            "total_hits": 1,
        }

    return AsyncMock(side_effect=_search)


@pytest.mark.asyncio
async def test_returning_user_latest_source_offer_searches_only_after_yes(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "playCount": 1,
        "lastToken": CONTENT_ID,
        "lastCompletedSource": {
            "contentId": CONTENT_ID,
            "organizationId": "org-york",
            "organizationName": "York Talking News",
        },
    }
    search = AsyncMock(return_value={
        "results": [_queued_content(SECOND_CONTENT_ID, "York weekly news")],
        "total_hits": 1,
    })
    monkeypatch.setattr(HearApiClient, "search", search)
    skill = build_skill(persistence)

    launch = await skill.invoke(_event({"type": "LaunchRequest"}, new=True), None)

    search.assert_not_awaited()
    assert "latest from York Talking News" in launch["response"]["outputSpeech"]["ssml"]
    assert persistence._store[USER_ID]["activeDialog"]["type"] == "latest_source"

    accepted = await skill.invoke(_event({
        "type": "IntentRequest",
        "intent": {"name": "AMAZON.YesIntent", "slots": {}},
    }), None)

    search.assert_awaited_once()
    payload = search.await_args.args[0]
    assert payload["filter"] == {"organizationIds": ["org-york"]}
    assert payload["sort"] == "latest"
    assert accepted["response"]["directives"][0]["audioItem"]["stream"]["token"] == SECOND_CONTENT_ID


@pytest.mark.asyncio
async def test_latest_source_offer_is_once_per_completed_item_and_no_clears_it(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "playCount": 1,
        "lastToken": CONTENT_ID,
        "lastCompletedSource": {
            "contentId": CONTENT_ID,
            "creatorId": "creator-1",
            "creatorName": "Sheffield Talking Newspaper",
        },
    }
    search = AsyncMock()
    monkeypatch.setattr("src.clients.hear.search", search)
    skill = build_skill(persistence)
    await skill.invoke(_event({"type": "LaunchRequest"}, new=True), None)

    declined = await skill.invoke(_event({
        "type": "IntentRequest",
        "intent": {"name": "AMAZON.NoIntent", "slots": {}},
    }), None)

    search.assert_not_awaited()
    assert persistence._store[USER_ID]["pendingLatestSource"] is None
    assert persistence._store[USER_ID]["activeDialog"] is None
    assert "news or sport" in declined["response"]["outputSpeech"]["ssml"]
    relaunched = await skill.invoke(_event({"type": "LaunchRequest"}, new=True), None)
    assert "Would you like to hear the latest" not in relaunched["response"]["outputSpeech"]["ssml"]


@pytest.mark.asyncio
async def test_independent_creator_latest_offer_uses_creator_name_and_id(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "playCount": 1,
        "lastToken": CONTENT_ID,
        "lastCompletedSource": {
            "contentId": CONTENT_ID,
            "organizationId": "org-independent",
            "organizationName": "Independent Creator",
            "creatorId": "creator-david",
            "creatorName": "David Beard",
        },
    }
    search = AsyncMock(return_value={
        "results": [_queued_content(SECOND_CONTENT_ID, "David's latest")],
        "total_hits": 1,
    })
    monkeypatch.setattr(HearApiClient, "search", search)
    skill = build_skill(persistence)

    launch = await skill.invoke(_event({"type": "LaunchRequest"}, new=True), None)
    assert "latest from David Beard" in launch["response"]["outputSpeech"]["ssml"]
    assert "Independent Creator" not in launch["response"]["outputSpeech"]["ssml"]

    await skill.invoke(_event({
        "type": "IntentRequest",
        "intent": {"name": "AMAZON.YesIntent", "slots": {}},
    }), None)
    assert search.await_args.args[0]["filter"] == {"creatorIds": ["creator-david"]}


@pytest.mark.asyncio
async def test_resume_yes_uses_persisted_playable_state_without_search(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "awaitingResume": True,
        "activePlayback": _playback_state(),
    }
    search = AsyncMock()
    monkeypatch.setattr("src.clients.hear.search", search)

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
        "src.handlers.audio.emit_listening_event",
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
        "src.handlers.audio.emit_listening_event",
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
        "src.handlers.audio.emit_listening_event",
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
        "src.handlers.audio.emit_listening_event",
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
async def test_queue_enqueues_second_and_third_with_progress_reports(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    second = _queued_content(SECOND_CONTENT_ID, "Second bulletin")
    third = _queued_content(THIRD_CONTENT_ID, "Third bulletin")
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=170_000),
        "playbackQueue": {
            "queueId": "queue-1",
            "source": "search",
            "orderedContentIds": [CONTENT_ID, SECOND_CONTENT_ID, THIRD_CONTENT_ID],
            "currentIndex": 0,
        },
    }
    monkeypatch.setattr(
        HearApiClient, "search",
        _fake_search([second, third]),
    )
    monkeypatch.setattr(
        "src.handlers.audio.emit_listening_event",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "src.handlers.audio.emit_listening_event",
        AsyncMock(),
    )

    first_result = await build_skill(persistence).invoke(
        _event({
            "type": "AudioPlayer.PlaybackNearlyFinished",
            "token": CONTENT_ID,
            "offsetInMilliseconds": 170_000,
        }),
        None,
    )
    first_stream = first_result["response"]["directives"][0]["audioItem"]["stream"]
    assert first_result["response"]["directives"][0]["playBehavior"] == "ENQUEUE"
    assert first_stream["token"] == SECOND_CONTENT_ID
    assert first_stream["expectedPreviousToken"] == CONTENT_ID
    assert "progressReportDelayInMilliseconds" in first_stream
    assert "progressReportIntervalInMilliseconds" in first_stream

    second_started = await build_skill(persistence).invoke(
        _event({
            "type": "AudioPlayer.PlaybackStarted",
            "token": SECOND_CONTENT_ID,
            "offsetInMilliseconds": 0,
        }),
        None,
    )
    assert persistence._store[USER_ID]["playbackQueue"]["currentIndex"] == 1
    started_stream = second_started["response"]["directives"][0]["audioItem"]["stream"]
    assert started_stream["token"] == THIRD_CONTENT_ID
    assert started_stream["expectedPreviousToken"] == SECOND_CONTENT_ID

    second_result = await build_skill(persistence).invoke(
        _event({
            "type": "AudioPlayer.PlaybackNearlyFinished",
            "token": SECOND_CONTENT_ID,
            "offsetInMilliseconds": 170_000,
        }),
        None,
    )
    assert second_result["response"].get("directives") is None


@pytest.mark.asyncio
async def test_playback_started_prefetches_second_when_nearly_finished_never_arrives(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    second = _queued_content(SECOND_CONTENT_ID, "Second bulletin")
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="starting", offset_ms=0),
        "playbackQueue": {
            "queueId": "queue-1",
            "source": "search",
            "orderedContentIds": [CONTENT_ID, SECOND_CONTENT_ID],
            "currentIndex": 0,
        },
    }
    monkeypatch.setattr(HearApiClient, "search", _fake_search([second]))
    monkeypatch.setattr("src.handlers.audio.emit_listening_event", AsyncMock())

    result = await build_skill(persistence).invoke(
        _event({
            "type": "AudioPlayer.PlaybackStarted",
            "token": CONTENT_ID,
            "offsetInMilliseconds": 0,
        }),
        None,
    )

    directive = result["response"]["directives"][0]
    stream = directive["audioItem"]["stream"]
    assert directive["playBehavior"] == "ENQUEUE"
    assert stream["token"] == SECOND_CONTENT_ID
    assert stream["expectedPreviousToken"] == CONTENT_ID
    assert persistence._store[USER_ID]["preparedNextContent"]["contentId"] == SECOND_CONTENT_ID


@pytest.mark.asyncio
async def test_queue_prefetch_falls_back_to_backend_search_when_no_cache_persisted(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    second = _queued_content(SECOND_CONTENT_ID, "Second bulletin")
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=170_000),
        "playbackQueue": {
            "queueId": "queue-1",
            "source": "search",
            "orderedContentIds": [CONTENT_ID, SECOND_CONTENT_ID],
            "currentIndex": 0,
        },
    }
    search = _fake_search([second])
    monkeypatch.setattr(
        HearApiClient, "search",
        search,
    )
    monkeypatch.setattr(
        "src.handlers.audio.emit_listening_event",
        AsyncMock(),
    )

    result = await build_skill(persistence).invoke(
        _event({
            "type": "AudioPlayer.PlaybackNearlyFinished",
            "token": CONTENT_ID,
            "offsetInMilliseconds": 170_000,
        }),
        None,
    )

    search.assert_awaited_once()
    assert search.await_args.args[0]["filter"] == {"contentIds": [SECOND_CONTENT_ID]}
    directive = result["response"]["directives"][0]
    assert directive["playBehavior"] == "ENQUEUE"
    assert directive["audioItem"]["stream"]["token"] == SECOND_CONTENT_ID
    assert directive["audioItem"]["stream"]["expectedPreviousToken"] == CONTENT_ID


@pytest.mark.asyncio
async def test_playback_finished_starts_next_when_prefetch_was_missed(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=179_000),
        "playbackQueue": {
            "queueId": "queue-1",
            "source": "search",
            "orderedContentIds": [CONTENT_ID, SECOND_CONTENT_ID],
            "currentIndex": 0,
        },
        "preparedNextContent": None,
    }
    monkeypatch.setattr(
        "src.handlers.audio.emit_listening_event",
        AsyncMock(),
    )
    fallback_response = {"directives": [{"type": "AudioPlayer.Play"}]}
    advance = AsyncMock(return_value=fallback_response)
    monkeypatch.setattr(
        "src.handlers.audio.play_next_queued_item",
        advance,
    )

    result = await build_skill(persistence).invoke(
        _event({
            "type": "AudioPlayer.PlaybackFinished",
            "token": CONTENT_ID,
            "offsetInMilliseconds": 180_000,
        }),
        None,
    )

    advance.assert_awaited_once()
    assert advance.await_args.kwargs == {"speak_intro": False}
    assert result["response"] == fallback_response


@pytest.mark.asyncio
async def test_playback_finished_accepts_raw_camel_case_offset(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=12_345),
    }
    monkeypatch.setattr(
        "src.handlers.audio.emit_listening_event",
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
