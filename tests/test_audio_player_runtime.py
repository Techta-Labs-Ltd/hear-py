from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.application import Application
from src.clients.hear import HearApiClient
from src.container import ApplicationContainer
from src.database.persistence import MemoryPersistenceAdapter
from src.models.user import User

USER_ID = "amzn1.ask.account.AUDIO_RUNTIME_TEST"
APPLICATION_ID = "amzn1.ask.skill.test"
CONTENT_ID = "11111111-1111-1111-1111-111111111111"
SECOND_CONTENT_ID = "22222222-2222-2222-2222-222222222222"
THIRD_CONTENT_ID = "33333333-3333-3333-3333-333333333333"


def _event(request: dict, *, new: bool = False) -> dict:
    request_id = f"audio-runtime-{request.get('type')}-{request.get('token')}-{request.get('offsetInMilliseconds')}"
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
            "requestId": request_id,
            "timestamp": "2026-07-29T12:00:00Z",
            "locale": "en-GB",
            **request,
        },
    }


def _playback_state(*, status: str = "paused", offset_ms: int = 42000) -> dict:
    return {
        "contentId": CONTENT_ID,
        "token": CONTENT_ID,
        "title": "Sheffield monthly bulletin",
        "creatorId": "creator-1",
        "creatorName": "Sheffield Talking Newspaper",
        "audioUrl": "https://cdn.hear.media/audio/monthly-bulletin.mp3",
        "durationMs": 180000,
        "offsetMs": offset_ms,
        "listenedMs": offset_ms,
        "sessionId": f"{CONTENT_ID}:session",
        "status": status,
        "startedAt": 1,
        "updatedAt": 1,
    }


def _stored_state(persistence: MemoryPersistenceAdapter) -> dict:
    return User.merge_persisted(persistence._store.get(USER_ID))


def _queued_content(content_id: str, title: str) -> dict:
    return {
        "contentId": content_id,
        "title": title,
        "spokenTitle": title,
        "creatorId": "creator-1",
        "creatorName": "Sheffield Talking Newspaper",
        "audioUrl": f"https://cdn.hear.media/audio/{content_id}.mp3",
        "durationMs": 180000,
        "playbackSpeeds": [],
    }


def _fake_search(catalog: list[dict]) -> AsyncMock:

    async def _search(payload, timeout_ms=None):
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
    search = AsyncMock(
        return_value={
            "results": [_queued_content(SECOND_CONTENT_ID, "York weekly news")],
            "total_hits": 1,
        }
    )
    monkeypatch.setattr(HearApiClient, "search", search)
    skill = Application.build_skill(persistence, deps=ApplicationContainer())
    launch = await skill.invoke(_event({"type": "LaunchRequest"}, new=True), None)
    search.assert_not_awaited()
    assert "latest from York Talking News" in launch["response"]["outputSpeech"]["ssml"]
    assert persistence._store[USER_ID]["activeDialog"]["type"] == "latest_source"
    accepted = await skill.invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "AMAZON.YesIntent", "slots": {}},
            }
        ),
        None,
    )
    search.assert_awaited_once()
    payload = search.await_args.args[0]
    assert payload["filter"] == {"organizationIds": ["org-york"]}
    assert payload["sort"] == "latest"
    assert (
        accepted["response"]["directives"][0]["audioItem"]["stream"]["token"] == SECOND_CONTENT_ID
    )


@pytest.mark.asyncio
async def test_latest_source_offer_is_once_per_completed_item_and_no_clears_it(
    monkeypatch,
):
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
    monkeypatch.setattr(HearApiClient, "search", search)
    skill = Application.build_skill(persistence, deps=ApplicationContainer())
    await skill.invoke(_event({"type": "LaunchRequest"}, new=True), None)
    declined = await skill.invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "AMAZON.NoIntent", "slots": {}},
            }
        ),
        None,
    )
    search.assert_not_awaited()
    assert _stored_state(persistence)["pendingLatestSource"] is None
    assert _stored_state(persistence)["activeDialog"] is None
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
    search = AsyncMock(
        return_value={
            "results": [_queued_content(SECOND_CONTENT_ID, "David's latest")],
            "total_hits": 1,
        }
    )
    monkeypatch.setattr(HearApiClient, "search", search)
    skill = Application.build_skill(persistence, deps=ApplicationContainer())
    launch = await skill.invoke(_event({"type": "LaunchRequest"}, new=True), None)
    assert "latest from David Beard" in launch["response"]["outputSpeech"]["ssml"]
    assert "Independent Creator" not in launch["response"]["outputSpeech"]["ssml"]
    await skill.invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "AMAZON.YesIntent", "slots": {}},
            }
        ),
        None,
    )
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
    monkeypatch.setattr(HearApiClient, "search", search)
    result = await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "AMAZON.YesIntent", "slots": {}},
            }
        ),
        None,
    )
    search.assert_not_awaited()
    response = result["response"]
    directive = response["directives"][0]
    assert directive["type"] == "AudioPlayer.Play"
    assert directive["audioItem"]["stream"]["token"] == CONTENT_ID
    assert directive["audioItem"]["stream"]["offsetInMilliseconds"] == 42000
    assert "Continuing where you stopped" in response["outputSpeech"]["ssml"]
    assert response["shouldEndSession"] is True


@pytest.mark.asyncio
async def test_paused_publication_track_resumes_exact_track_and_offset(monkeypatch):
    publication_id = "c9a03c82-394f-4e4c-822d-598169639395"
    track_id = SECOND_CONTENT_ID
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "playbackQueue": {
            "queueId": "queue-1",
            "source": "publication",
            "publicationId": publication_id,
            "publicationTitle": None,
            "publicationTrackCount": 5,
            "orderedContentIds": [CONTENT_ID, track_id, THIRD_CONTENT_ID],
            "currentIndex": 1,
        },
        "activePlayback": {
            **_playback_state(status="playing", offset_ms=12000),
            "contentId": track_id,
            "token": track_id,
            "title": "04_Mole_Valley_Life_Digital_Switch",
            "publicationId": publication_id,
            "publicationTitle": None,
            "subjectType": "publication",
            "subjectId": publication_id,
            "trackContentId": track_id,
            "trackIndex": 1,
            "trackCount": 5,
            "sessionId": f"{track_id}:session",
            "subjectSessionId": f"publication:{publication_id}:queue-1",
            "audioUrl": f"https://cdn.hear.media/audio/{track_id}.mp3",
        },
    }
    search = _fake_search([_queued_content(THIRD_CONTENT_ID, "Next publication track")])
    monkeypatch.setattr(HearApiClient, "search", search)
    monkeypatch.setattr("src.models.playback.Playback.emit", AsyncMock())
    skill = Application.build_skill(persistence, deps=ApplicationContainer())

    await skill.invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackStopped",
                "token": track_id,
                "offsetInMilliseconds": 73000,
            }
        ),
        None,
    )

    paused = _stored_state(persistence)["activePlayback"]
    assert paused["status"] == "paused"
    assert paused["contentId"] == track_id
    assert paused["trackContentId"] == track_id
    assert paused["subjectId"] == publication_id
    assert paused["offsetMs"] == 73000

    launch = await skill.invoke(_event({"type": "LaunchRequest"}, new=True), None)
    assert "that publication" in launch["response"]["outputSpeech"]["ssml"]
    assert persistence._store[USER_ID]["awaitingResume"] is True

    resumed = await skill.invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "AMAZON.YesIntent", "slots": {}},
            }
        ),
        None,
    )

    stream = resumed["response"]["directives"][0]["audioItem"]["stream"]
    assert stream["token"] == track_id
    assert stream["offsetInMilliseconds"] == 73000
    active = _stored_state(persistence)["activePlayback"]
    assert active["subjectType"] == "publication"
    assert active["subjectId"] == publication_id
    assert active["trackContentId"] == track_id

    enqueued = await skill.invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackNearlyFinished",
                "token": track_id,
                "offsetInMilliseconds": 170000,
            }
        ),
        None,
    )
    next_stream = enqueued["response"]["directives"][0]["audioItem"]["stream"]
    assert next_stream["token"] == THIRD_CONTENT_ID
    prepared = persistence._store[USER_ID]["preparedNextContent"]
    assert prepared["publicationId"] == publication_id
    assert prepared["contentId"] == THIRD_CONTENT_ID
    assert "subjectType" not in prepared
    assert "trackContentId" not in prepared
    assert prepared["trackIndex"] == 2
    assert prepared["trackCount"] == 5

    await skill.invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackStarted",
                "token": THIRD_CONTENT_ID,
                "offsetInMilliseconds": 0,
            }
        ),
        None,
    )

    continued = _stored_state(persistence)["activePlayback"]
    assert continued["contentId"] == THIRD_CONTENT_ID
    assert continued["publicationId"] == publication_id
    assert continued["subjectId"] == publication_id
    assert continued["trackContentId"] == THIRD_CONTENT_ID
    assert continued["trackIndex"] == 2
    assert continued["trackCount"] == 5


@pytest.mark.asyncio
async def test_resume_no_abandons_playback_and_offers_next_listening_options():
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "awaitingResume": True,
        "activePlayback": _playback_state(),
    }
    result = await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "AMAZON.NoIntent", "slots": {}},
            }
        ),
        None,
    )
    response = result["response"]
    state = _stored_state(persistence)
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
        "activePlayback": _playback_state(offset_ms=120000),
        "feedbackCandidates": [
            {
                "feedbackKey": CONTENT_ID,
                "contentId": CONTENT_ID,
                "listenedMs": 120000,
                "completed": False,
                "sessionId": f"{CONTENT_ID}:session",
            }
        ],
    }
    await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "AMAZON.NoIntent", "slots": {}},
            }
        ),
        None,
    )
    state = persistence._store[USER_ID]
    assert state.get("awaitingFeedback") is not True
    assert state.get("pendingFeedback") is None


@pytest.mark.asyncio
async def test_increase_speed_after_resume_decline_does_not_restart_abandoned_track():
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "awaitingResume": True,
        "playbackSpeed": 1.0,
        "currentPlaybackSpeeds": [
            {"speed": 1.0, "audioUrl": "https://cdn.hear.media/normal.mp3"},
            {"speed": 1.5, "audioUrl": "https://cdn.hear.media/faster.mp3"},
        ],
        "activePlayback": _playback_state(),
        "playbackQueue": {
            "queueId": "queue-1",
            "source": "search",
            "orderedContentIds": [CONTENT_ID, SECOND_CONTENT_ID],
            "currentIndex": 0,
        },
    }
    skill = Application.build_skill(persistence, deps=ApplicationContainer())
    await skill.invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "AMAZON.NoIntent", "slots": {}},
            }
        ),
        None,
    )
    result = await skill.invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "IncreaseSpeedIntent", "slots": {}},
            }
        ),
        None,
    )
    state = _stored_state(persistence)
    response = result["response"]
    assert state["playbackSpeed"] == 1.5
    assert state["activePlayback"]["status"] == "abandoned"
    assert state["playbackQueue"]["currentIndex"] == 0
    assert response.get("directives") is None
    assert "What would you like to listen to next?" in response["outputSpeech"]["ssml"]
    assert response["shouldEndSession"] is False


@pytest.mark.asyncio
async def test_increase_speed_restarts_paused_track_at_saved_offset():
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "playbackSpeed": 1.0,
        "currentPlaybackSpeeds": [
            {"speed": 1.0, "audioUrl": "https://cdn.hear.media/normal.mp3"},
            {"speed": 1.5, "audioUrl": "https://cdn.hear.media/faster.mp3"},
        ],
        "activePlayback": _playback_state(status="paused", offset_ms=42000),
    }
    result = await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "IncreaseSpeedIntent", "slots": {}},
            }
        ),
        None,
    )
    response = result["response"]
    directive = response["directives"][0]
    assert persistence._store[USER_ID]["playbackSpeed"] == 1.5
    assert directive["type"] == "AudioPlayer.Play"
    assert directive["audioItem"]["stream"]["offsetInMilliseconds"] == 42000
    assert directive["audioItem"]["stream"]["url"] == "https://cdn.hear.media/faster.mp3"
    assert response["shouldEndSession"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "starting_speed", "expected_speed", "expected_url"),
    [
        (
            "IncreaseSpeedIntent",
            1.0,
            1.5,
            "https://cdn.hear.media/faster.mp3",
        ),
        (
            "DecreaseSpeedIntent",
            1.5,
            1.0,
            "https://cdn.hear.media/audio/monthly-bulletin.mp3",
        ),
    ],
)
async def test_speed_control_bypasses_pending_feedback(
    intent_name, starting_speed, expected_speed, expected_url
):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "playbackSpeed": starting_speed,
        "currentPlaybackSpeeds": [
            {"speed": 1.0, "audioUrl": "https://cdn.hear.media/normal.mp3"},
            {"speed": 1.5, "audioUrl": "https://cdn.hear.media/faster.mp3"},
        ],
        "activePlayback": _playback_state(status="playing", offset_ms=42000),
        "awaitingFeedback": True,
        "pendingFeedback": {
            "feedbackKey": "older-content",
            "contentId": "older-content",
            "completed": True,
        },
        "activeDialog": {
            "type": "feedback",
            "context": {"contentId": "older-content"},
            "expiresAt": 4102444800,
        },
    }

    result = await Application.build_skill(
        persistence,
        deps=ApplicationContainer(),
    ).invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": intent_name, "slots": {}},
            }
        ),
        None,
    )

    response = result["response"]
    assert _stored_state(persistence)["playbackSpeed"] == expected_speed
    assert response["directives"][0]["type"] == "AudioPlayer.Play"
    assert response["directives"][0]["audioItem"]["stream"]["url"] == expected_url
    assert "feedback question" not in response["outputSpeech"]["ssml"]
    assert persistence._store[USER_ID]["awaitingFeedback"] is True


@pytest.mark.asyncio
async def test_rate_this_content_opens_short_feedback_prompt_for_active_audio():
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=42000),
    }

    rate_event = _event(
        {
            "type": "IntentRequest",
            "intent": {"name": "RateContentIntent", "slots": {}},
        }
    )
    rate_event["context"]["AudioPlayer"] = {
        "playerActivity": "PLAYING",
        "token": CONTENT_ID,
        "offsetInMilliseconds": 57000,
    }
    result = await Application.build_skill(
        persistence,
        deps=ApplicationContainer(),
    ).invoke(
        rate_event,
        None,
    )

    response = result["response"]
    state = persistence._store[USER_ID]
    assert "Did you enjoy Sheffield monthly bulletin?" in response["outputSpeech"]["ssml"]
    assert response["shouldEndSession"] is False
    assert response["directives"] == [{"type": "AudioPlayer.Stop"}]
    assert state["awaitingFeedback"] is True
    assert state["pendingFeedback"]["contentId"] == CONTENT_ID
    assert state["pendingFeedback"]["requested"] is True
    assert state["activePlayback"]["status"] == "paused"
    assert state["activePlayback"]["offsetMs"] == 57000

    follow_up = await Application.build_skill(
        persistence,
        deps=ApplicationContainer(),
    ).invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "FeedbackEnjoyedIntent", "slots": {}},
            }
        ),
        None,
    )

    assert follow_up["response"]["outputSpeech"]
    assert follow_up["response"]["directives"][0]["type"] == "AudioPlayer.Play"
    assert (
        follow_up["response"]["directives"][0]["audioItem"]["stream"][
            "offsetInMilliseconds"
        ]
        == 57000
    )
    state = _stored_state(persistence)
    assert "feedbackHistory" not in persistence._store[USER_ID]
    assert state["awaitingFeedback"] is False
    assert state.get("awaitingFollow") is not True


@pytest.mark.asyncio
async def test_publication_rating_names_publication_when_prompting_and_resuming():
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": {
            **_playback_state(status="playing", offset_ms=42000),
            "title": "Track seven",
            "publicationId": "publication-1",
            "publicationTitle": "The Weekly Edition",
            "subjectType": "publication",
            "subjectTitle": "The Weekly Edition",
        },
    }
    skill = Application.build_skill(persistence, deps=ApplicationContainer())

    prompted = await skill.invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "RateContentIntent", "slots": {}},
            }
        ),
        None,
    )

    assert "Did you enjoy The Weekly Edition?" in prompted["response"]["outputSpeech"]["ssml"]
    assert "Track seven" not in prompted["response"]["outputSpeech"]["ssml"]
    assert persistence._store[USER_ID]["pendingFeedback"]["subjectType"] == "publication"
    assert (
        persistence._store[USER_ID]["pendingFeedback"]["feedbackKey"]
        == "publication:publication-1"
    )

    answered = await Application.build_skill(
        persistence,
        deps=ApplicationContainer(),
    ).invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "FeedbackEnjoyedIntent", "slots": {}},
            }
        ),
        None,
    )

    assert "Resuming The Weekly Edition" in answered["response"]["outputSpeech"]["ssml"]


@pytest.mark.asyncio
async def test_skipping_requested_rating_resumes_active_audio():
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=42000),
    }
    skill = Application.build_skill(persistence, deps=ApplicationContainer())
    await skill.invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "RateContentIntent", "slots": {}},
            }
        ),
        None,
    )

    result = await skill.invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "SkipFeedbackIntent", "slots": {}},
            }
        ),
        None,
    )

    response = result["response"]
    assert response["directives"][0]["type"] == "AudioPlayer.Play"
    assert response["directives"][0]["audioItem"]["stream"]["offsetInMilliseconds"] == 42000
    state = _stored_state(persistence)
    assert "feedbackHistory" not in persistence._store[USER_ID]
    assert state["awaitingFeedback"] is False


@pytest.mark.asyncio
async def test_requested_not_enjoyed_then_skip_resumes_active_audio():
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=42000),
    }
    skill = Application.build_skill(persistence, deps=ApplicationContainer())
    await skill.invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "RateContentIntent", "slots": {}},
            }
        ),
        None,
    )
    await skill.invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "FeedbackNotEnjoyedIntent", "slots": {}},
            }
        ),
        None,
    )

    result = await skill.invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "SkipFeedbackIntent", "slots": {}},
            }
        ),
        None,
    )

    response = result["response"]
    assert response["directives"][0]["type"] == "AudioPlayer.Play"
    assert response["directives"][0]["audioItem"]["stream"]["offsetInMilliseconds"] == 42000
    assert _stored_state(persistence)["awaitingReportDecision"] is False


@pytest.mark.asyncio
async def test_report_command_pauses_audio_and_yes_resumes_from_current_offset():
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=42000),
    }
    skill = Application.build_skill(persistence, deps=ApplicationContainer())
    report_event = _event(
        {
            "type": "IntentRequest",
            "intent": {"name": "ReportContentIntent", "slots": {}},
        }
    )
    report_event["context"]["AudioPlayer"] = {
        "playerActivity": "PLAYING",
        "token": CONTENT_ID,
        "offsetInMilliseconds": 63000,
    }

    reported = await skill.invoke(report_event, None)

    assert reported["response"]["directives"] == [{"type": "AudioPlayer.Stop"}]
    assert persistence._store[USER_ID]["activePlayback"]["status"] == "paused"
    assert persistence._store[USER_ID]["activePlayback"]["offsetMs"] == 63000
    assert persistence._store[USER_ID]["awaitingContinueAfterFlag"] is True

    continued = await skill.invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "AMAZON.YesIntent", "slots": {}},
            }
        ),
        None,
    )

    directive = continued["response"]["directives"][0]
    assert directive["type"] == "AudioPlayer.Play"
    assert directive["audioItem"]["stream"]["offsetInMilliseconds"] == 63000
    assert _stored_state(persistence)["awaitingContinueAfterFlag"] is False


@pytest.mark.asyncio
async def test_report_publication_names_publication_when_asking_and_continuing():
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": {
            **_playback_state(status="playing", offset_ms=42000),
            "title": "Track seven",
            "publicationId": "publication-1",
            "publicationTitle": "The Weekly Edition",
            "subjectType": "publication",
            "subjectTitle": "The Weekly Edition",
        },
    }
    report_event = _event(
        {
            "type": "IntentRequest",
            "intent": {"name": "ReportContentIntent", "slots": {}},
        }
    )
    report_event["context"]["AudioPlayer"] = {
        "playerActivity": "PLAYING",
        "token": CONTENT_ID,
        "offsetInMilliseconds": 63000,
    }

    reported = await Application.build_skill(
        persistence,
        deps=ApplicationContainer(),
    ).invoke(report_event, None)

    assert "keep listening to The Weekly Edition" in reported["response"]["outputSpeech"]["ssml"]
    assert "Track seven" not in reported["response"]["outputSpeech"]["ssml"]

    continued = await Application.build_skill(
        persistence,
        deps=ApplicationContainer(),
    ).invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "AMAZON.YesIntent", "slots": {}},
            }
        ),
        None,
    )

    assert "continuing The Weekly Edition" in continued["response"]["outputSpeech"]["ssml"]


@pytest.mark.asyncio
async def test_bare_normal_speed_resets_to_base_audio_without_speed_slot():
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "playbackSpeed": 1.5,
        "currentPlaybackSpeeds": [{"speed": 1.5, "audioUrl": "https://cdn.hear.media/faster.mp3"}],
        "activePlayback": {
            **_playback_state(status="paused", offset_ms=42000),
            "audioUrl": "https://cdn.hear.media/normal.mp3",
            "playbackSpeeds": [{"speed": 1.5, "audioUrl": "https://cdn.hear.media/faster.mp3"}],
        },
    }
    result = await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event(
            {
                "type": "IntentRequest",
                "intent": {"name": "SetPlaybackSpeedIntent", "slots": {}},
            }
        ),
        None,
    )
    response = result["response"]
    directive = response["directives"][0]
    assert _stored_state(persistence)["playbackSpeed"] == 1.0
    assert directive["audioItem"]["stream"]["offsetInMilliseconds"] == 42000
    assert directive["audioItem"]["stream"]["url"] == "https://cdn.hear.media/normal.mp3"
    assert "reset to normal" in response["outputSpeech"]["ssml"]


@pytest.mark.asyncio
async def test_playback_started_accepts_raw_camel_case_offset(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="starting", offset_ms=0),
    }
    monkeypatch.setattr("src.models.playback.Playback.emit", AsyncMock())
    await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackStarted",
                "token": CONTENT_ID,
                "offsetInMilliseconds": 12345,
            }
        ),
        None,
    )
    state = persistence._store[USER_ID]["activePlayback"]
    assert state["status"] == "playing"
    assert state["offsetMs"] == 12345
    assert state["listenedMs"] == 12345


@pytest.mark.parametrize(
    "event_type",
    [
        "AudioPlayer.PlaybackProgressReportDelayPassed",
        "AudioPlayer.PlaybackProgressReportIntervalPassed",
    ],
)
@pytest.mark.asyncio
async def test_playback_progress_events_persist_and_sync(monkeypatch, event_type):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=12345),
    }
    emit = AsyncMock()
    monkeypatch.setattr("src.models.playback.Playback.emit", emit)
    await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event({"type": event_type, "token": CONTENT_ID, "offsetInMilliseconds": 91000}),
        None,
    )
    state = persistence._store[USER_ID]["activePlayback"]
    assert state["offsetMs"] == 91000
    assert state["listenedMs"] == 91000
    emit.assert_awaited_once()
    assert emit.await_args.args[1] == "progress"


@pytest.mark.asyncio
async def test_playback_stopped_never_creates_feedback_candidate(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=120000),
    }
    monkeypatch.setattr("src.models.playback.Playback.emit", AsyncMock())
    await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackStopped",
                "token": CONTENT_ID,
                "offsetInMilliseconds": 120000,
            }
        ),
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
        "activePlayback": _playback_state(status="playing", offset_ms=170000),
    }
    emit = AsyncMock()
    monkeypatch.setattr("src.models.playback.Playback.emit", emit)
    await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackNearlyFinished",
                "token": CONTENT_ID,
                "offsetInMilliseconds": 170000,
            }
        ),
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
        "activePlayback": _playback_state(status="playing", offset_ms=170000),
        "playbackQueue": {
            "queueId": "queue-1",
            "source": "search",
            "orderedContentIds": [CONTENT_ID, SECOND_CONTENT_ID, THIRD_CONTENT_ID],
            "currentIndex": 0,
        },
    }
    monkeypatch.setattr(HearApiClient, "search", _fake_search([second, third]))
    monkeypatch.setattr("src.models.playback.Playback.emit", AsyncMock())
    monkeypatch.setattr("src.models.playback.Playback.emit", AsyncMock())
    first_result = await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackNearlyFinished",
                "token": CONTENT_ID,
                "offsetInMilliseconds": 170000,
            }
        ),
        None,
    )
    first_stream = first_result["response"]["directives"][0]["audioItem"]["stream"]
    assert first_result["response"]["directives"][0]["playBehavior"] == "ENQUEUE"
    assert first_stream["token"] == SECOND_CONTENT_ID
    assert first_stream["expectedPreviousToken"] == CONTENT_ID
    assert "progressReportDelayInMilliseconds" in first_stream
    assert "progressReportIntervalInMilliseconds" in first_stream
    second_started = await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackStarted",
                "token": SECOND_CONTENT_ID,
                "offsetInMilliseconds": 0,
            }
        ),
        None,
    )
    assert persistence._store[USER_ID]["playbackQueue"]["currentIndex"] == 1
    assert second_started["response"].get("directives") is None
    second_result = await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackNearlyFinished",
                "token": SECOND_CONTENT_ID,
                "offsetInMilliseconds": 170000,
            }
        ),
        None,
    )
    second_stream = second_result["response"]["directives"][0]["audioItem"]["stream"]
    assert second_stream["token"] == THIRD_CONTENT_ID
    assert second_stream["expectedPreviousToken"] == SECOND_CONTENT_ID
    assert "progressReportDelayInMilliseconds" in second_stream


@pytest.mark.asyncio
async def test_playback_started_does_not_return_prohibited_play_directive(monkeypatch):
    persistence = MemoryPersistenceAdapter()
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
    monkeypatch.setattr("src.models.playback.Playback.emit", AsyncMock())
    result = await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackStarted",
                "token": CONTENT_ID,
                "offsetInMilliseconds": 0,
            }
        ),
        None,
    )
    assert result["response"].get("directives") is None
    assert persistence._store[USER_ID].get("preparedNextContent") is None


@pytest.mark.asyncio
async def test_queue_prefetch_falls_back_to_backend_search_when_no_cache_persisted(
    monkeypatch,
):
    persistence = MemoryPersistenceAdapter()
    second = _queued_content(SECOND_CONTENT_ID, "Second bulletin")
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=170000),
        "playbackQueue": {
            "queueId": "queue-1",
            "source": "search",
            "orderedContentIds": [CONTENT_ID, SECOND_CONTENT_ID],
            "currentIndex": 0,
        },
    }
    search = _fake_search([second])
    monkeypatch.setattr(HearApiClient, "search", search)
    monkeypatch.setattr("src.models.playback.Playback.emit", AsyncMock())
    result = await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackNearlyFinished",
                "token": CONTENT_ID,
                "offsetInMilliseconds": 170000,
            }
        ),
        None,
    )
    search.assert_awaited_once()
    assert search.await_args.args[0]["filter"] == {"contentIds": [SECOND_CONTENT_ID]}
    directive = result["response"]["directives"][0]
    assert directive["playBehavior"] == "ENQUEUE"
    assert directive["audioItem"]["stream"]["token"] == SECOND_CONTENT_ID
    assert directive["audioItem"]["stream"]["expectedPreviousToken"] == CONTENT_ID


@pytest.mark.asyncio
async def test_queue_enqueue_uses_listener_playback_speed(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    second = _queued_content(SECOND_CONTENT_ID, "Second bulletin")
    second["playbackSpeeds"] = [
        {"speed": 1.5, "audioUrl": "https://cdn.hear.media/audio/second-1-5.mp3"}
    ]
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "playbackSpeed": 1.5,
        "activePlayback": _playback_state(status="playing", offset_ms=170000),
        "playbackQueue": {
            "queueId": "queue-1",
            "source": "search",
            "orderedContentIds": [CONTENT_ID, SECOND_CONTENT_ID],
            "currentIndex": 0,
        },
    }
    monkeypatch.setattr(HearApiClient, "search", _fake_search([second]))
    monkeypatch.setattr("src.models.playback.Playback.emit", AsyncMock())
    result = await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackNearlyFinished",
                "token": CONTENT_ID,
                "offsetInMilliseconds": 170000,
            }
        ),
        None,
    )
    stream = result["response"]["directives"][0]["audioItem"]["stream"]
    assert stream["url"] == "https://cdn.hear.media/audio/second-1-5.mp3"


@pytest.mark.asyncio
async def test_older_playback_event_cannot_regress_newer_state(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": {
            **_playback_state(status="playing", offset_ms=90000),
            "eventTimestamp": 1785326400000,
            "lastEventRequestId": "newer-event",
        },
        "lastOffsetMs": 90000,
    }
    monkeypatch.setattr("src.models.playback.Playback.emit", AsyncMock())
    event = _event(
        {
            "type": "AudioPlayer.PlaybackStopped",
            "requestId": "older-event",
            "timestamp": "2026-07-28T12:00:00Z",
            "token": CONTENT_ID,
            "offsetInMilliseconds": 10000,
        }
    )
    await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(event, None)
    state = persistence._store[USER_ID]
    assert state["activePlayback"]["status"] == "playing"
    assert state["activePlayback"]["offsetMs"] == 90000
    assert state["lastOffsetMs"] == 90000


@pytest.mark.asyncio
async def test_duplicate_playback_event_is_idempotent(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=10000),
        "lastOffsetMs": 10000,
    }
    emit = AsyncMock()
    monkeypatch.setattr("src.models.playback.Playback.emit", emit)
    event = _event(
        {
            "type": "AudioPlayer.PlaybackProgressReportIntervalPassed",
            "requestId": "same-event",
            "token": CONTENT_ID,
            "offsetInMilliseconds": 20000,
        }
    )
    skill = Application.build_skill(persistence, deps=ApplicationContainer())
    await skill.invoke(event, None)
    await skill.invoke(event, None)
    assert persistence._store[USER_ID]["activePlayback"]["offsetMs"] == 20000
    assert emit.await_count == 1


@pytest.mark.asyncio
async def test_listening_time_uses_event_elapsed_time_and_does_not_count_seeks(
    monkeypatch,
):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": {
            **_playback_state(status="starting", offset_ms=0),
            "timeSpentMs": 0,
            "observationOffsetMs": 0,
            "observationTimestampMs": 0,
        },
    }
    monkeypatch.setattr("src.models.playback.Playback.emit", AsyncMock())
    skill = Application.build_skill(persistence, deps=ApplicationContainer())

    events = [
        ("AudioPlayer.PlaybackStarted", "2026-07-29T12:00:00Z", 0),
        ("AudioPlayer.PlaybackProgressReportIntervalPassed", "2026-07-29T12:00:30Z", 30000),
        ("AudioPlayer.PlaybackProgressReportIntervalPassed", "2026-07-29T12:00:35Z", 120000),
        ("AudioPlayer.PlaybackProgressReportIntervalPassed", "2026-07-29T12:00:40Z", 60000),
        ("AudioPlayer.PlaybackProgressReportIntervalPassed", "2026-07-29T12:00:50Z", 70000),
    ]
    for index, (request_type, timestamp, offset) in enumerate(events):
        await skill.invoke(
            _event(
                {
                    "type": request_type,
                    "requestId": f"elapsed-listening-{index}",
                    "timestamp": timestamp,
                    "token": CONTENT_ID,
                    "offsetInMilliseconds": offset,
                }
            ),
            None,
        )

    state = _stored_state(persistence)["activePlayback"]
    assert state["listenedMs"] == 120000
    assert state["timeSpentMs"] == 45000
    assert state["timeSpentHours"] == 0.0125
    history = persistence._store[USER_ID]["playHistory"][0]
    assert history["timeSpentMs"] == 45000
    assert "sessions" not in history


@pytest.mark.asyncio
async def test_playback_finished_does_not_return_prohibited_play_directive(monkeypatch, caplog):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=179000),
        "playbackQueue": {
            "queueId": "queue-1",
            "source": "search",
            "orderedContentIds": [CONTENT_ID, SECOND_CONTENT_ID],
            "currentIndex": 0,
        },
        "preparedNextContent": None,
    }
    monkeypatch.setattr("src.models.playback.Playback.emit", AsyncMock())
    with caplog.at_level("WARNING", logger="src.controllers.playback_events"):
        result = await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
            _event(
                {
                    "type": "AudioPlayer.PlaybackFinished",
                    "token": CONTENT_ID,
                    "offsetInMilliseconds": 180000,
                }
            ),
            None,
        )
    assert result["response"].get("directives") is None
    assert "without an accepted PlaybackNearlyFinished enqueue" in caplog.text
    state = persistence._store[USER_ID]
    assert state["awaitingFeedback"] is True
    assert state["pendingFeedback"]["contentId"] == CONTENT_ID


@pytest.mark.asyncio
async def test_playback_finished_accepts_raw_camel_case_offset(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="playing", offset_ms=12345),
    }
    monkeypatch.setattr("src.models.playback.Playback.emit", AsyncMock())
    await Application.build_skill(persistence, deps=ApplicationContainer()).invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackFinished",
                "token": CONTENT_ID,
                "offsetInMilliseconds": 179500,
            }
        ),
        None,
    )
    state = persistence._store[USER_ID]["activePlayback"]
    assert state["status"] == "completed"
    assert state["offsetMs"] == 180000
    assert state["listenedMs"] == 180000
    pending = persistence._store[USER_ID]["pendingFeedback"]
    assert pending["feedbackKey"] == CONTENT_ID
    assert pending["completed"] is True


@pytest.mark.asyncio
async def test_new_completion_replaces_old_feedback_before_relaunch():
    persistence = MemoryPersistenceAdapter()
    pendle_id = "44444444-4444-4444-4444-444444444444"
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "playCount": 2,
        "awaitingFeedback": True,
        "pendingFeedback": {
            "feedbackKey": CONTENT_ID,
            "contentId": CONTENT_ID,
            "title": "029_Car_park",
            "organizationName": "York Talking News",
            "playbackStartedAt": 10,
            "createdAt": 20,
            "completed": True,
        },
        "activeDialog": {"type": "feedback", "context": {"contentId": CONTENT_ID}},
        "activePlayback": {
            "contentId": pendle_id,
            "token": pendle_id,
            "title": "Pendle weekly update",
            "organizationId": "org-pendle",
            "organizationName": "Pendle Voice",
            "audioUrl": "https://cdn.hear.media/audio/pendle.mp3",
            "durationMs": 180000,
            "offsetMs": 175000,
            "listenedMs": 175000,
            "sessionId": f"{pendle_id}:session",
            "status": "playing",
            "startedAt": 30,
            "updatedAt": 31,
        },
    }
    skill = Application.build_skill(persistence, deps=ApplicationContainer())
    await skill.invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackFinished",
                "token": pendle_id,
                "offsetInMilliseconds": 180000,
            }
        ),
        None,
    )
    launch = await skill.invoke(_event({"type": "LaunchRequest"}, new=True), None)
    state = persistence._store[USER_ID]
    assert state["pendingFeedback"]["contentId"] == pendle_id
    speech = launch["response"]["outputSpeech"]["ssml"]
    assert "Pendle weekly update" in speech
    assert "Pendle Voice" in speech
    assert "029_Car_park" not in speech
