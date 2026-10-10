import copy
import datetime
from unittest.mock import AsyncMock

import pytest

from src.alexa.launch import LaunchWorkflow
from src.alexa.onboarding import LaunchTracker
from src.application import Application
from src.clients.hear import HearApiClient
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.database.persistence import MemoryPersistenceAdapter
from src.models.user import User
from tests.test_audio_player_runtime import USER_ID, _event

PUBLICATION_ID = "pub-tree"
TRACKS = ["track-1", "track-2"]


def _track(index: int) -> dict:
    return {
        "contentId": TRACKS[index],
        "title": f"Track__00{index + 1}",
        "publicationId": PUBLICATION_ID,
        "publicationTitle": "Tree Planting",
        "isPublication": True,
        "trackIndex": index,
        "trackCount": len(TRACKS),
        "organizationId": "org-green",
        "organizationName": "Green Voices Talking News",
        "creatorId": "creator-green",
        "creatorName": "Green Voices Talking News",
        "audioUrl": f"https://cdn.hear.media/{TRACKS[index]}.mp3",
        "durationMs": 120000,
    }


def test_publication_progress_is_saved_between_requests():
    assert StateSchema.scope_for("publicationFeedbackProgress") == StateSchema.PLAYBACK_SCOPE
    assert "publicationFeedbackProgress" not in StateSchema.LEGACY_DATABASE_FIELDS


@pytest.mark.asyncio
async def test_finishing_a_multi_track_publication_asks_for_feedback(monkeypatch):
    monkeypatch.setattr(
        HearApiClient,
        "resolve_listener_identity",
        AsyncMock(return_value={"listenerId": "listener-1"}),
    )
    monkeypatch.setattr(LaunchTracker, "record", lambda *_args: {"save": {}})
    for name in ("_ensure_listener_data_for_launch", "_sync_listener_for_launch"):
        monkeypatch.setattr(LaunchWorkflow, name, AsyncMock(side_effect=lambda _hi, store: store))
    monkeypatch.setattr("src.alexa.playback_workflow.Playback.emit", AsyncMock())
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "listenerId": "listener-1",
        "playCount": 3,
        "playbackQueue": {
            "queueId": "queue-1",
            "currentIndex": 0,
            "orderedContentIds": list(TRACKS),
            "publicationId": PUBLICATION_ID,
            "publicationTitle": "Tree Planting",
            "publicationTrackCount": len(TRACKS),
            "organizationId": "org-green",
            "organizationName": "Green Voices Talking News",
            "discoveryContext": {"kind": "publication", "name": "Tree Planting"},
            "contentCache": {content_id: _track(i) for i, content_id in enumerate(TRACKS)},
        },
        "activePlayback": {
            **_track(0),
            "token": TRACKS[0],
            "status": "playing",
            "offsetMs": 1000,
            "listenedMs": 1000,
            "queueId": "queue-1",
            "queueIndex": 0,
            "sessionId": f"{TRACKS[0]}:session",
            "startedAt": 1,
            "updatedAt": 1,
        },
    }
    clock = {"seconds": 0}

    async def send(request: dict, *, new: bool = False) -> dict:
        clock["seconds"] += 30
        event = _event(request, new=new)
        moment = datetime.datetime(2026, 10, 10, 9, 0) + datetime.timedelta(seconds=clock["seconds"])
        event["request"]["timestamp"] = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
        event["request"]["requestId"] = f"request-{clock['seconds']}"
        skill = Application.build_skill(persistence, container=ApplicationContainer())
        return (await skill.invoke(event, None))["response"]

    def audio(kind: str, token: str, offset: int) -> dict:
        return {"type": f"AudioPlayer.{kind}", "token": token, "offsetInMilliseconds": offset}

    await send(audio("PlaybackNearlyFinished", TRACKS[0], 110000))
    await send(audio("PlaybackFinished", TRACKS[0], 120000))
    saved_key = next(key for key in persistence._store if key != USER_ID)
    saved = User.merge_persisted(copy.deepcopy(persistence._store[saved_key]))
    assert TRACKS[0] in saved["publicationFeedbackProgress"][PUBLICATION_ID]["tracks"]

    await send(audio("PlaybackStarted", TRACKS[1], 0))
    await send(audio("PlaybackNearlyFinished", TRACKS[1], 110000))
    await send(audio("PlaybackFinished", TRACKS[1], 120000))
    launch = await send({"type": "LaunchRequest"}, new=True)

    spoken = launch["outputSpeech"]["ssml"]
    assert "Before we continue — did you enjoy Tree Planting from Green Voices Talking News?" in spoken


def test_rating_a_track_does_not_hide_it_from_publication_progress(mock_handler_input):
    from src.alexa.feedback_service import FeedbackService

    state = {
        **_track(0),
        "status": "completed",
        "listenedMs": 120000,
        "feedbackAnswered": True,
        "startedAt": 1,
    }
    FeedbackService.record_candidate(mock_handler_input, state, completed=True)

    progress = User.snapshot(mock_handler_input)["publicationFeedbackProgress"][PUBLICATION_ID]
    assert TRACKS[0] in progress["tracks"]


def test_publication_with_a_file_style_title_still_gets_feedback(mock_handler_input):
    from src.alexa.feedback import AlexaFeedback
    from src.alexa.feedback_service import FeedbackService

    for index in range(len(TRACKS)):
        state = {
            **_track(index),
            "publicationTitle": "Weekly_Edition_12",
            "status": "completed",
            "listenedMs": 120000,
            "startedAt": index + 1,
        }
        candidate = FeedbackService.record_candidate(mock_handler_input, state, completed=True)

    assert candidate is not None
    assert AlexaFeedback.feedback_subject(candidate, {}) == "a publication from Green Voices Talking News"
