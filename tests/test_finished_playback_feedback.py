from unittest.mock import AsyncMock

import pytest

from src.alexa.launch import LaunchWorkflow
from src.alexa.onboarding import LaunchTracker
from src.alexa.playback_state import PlaybackState
from src.alexa.speech import Speech
from src.application import Application
from src.clients.hear import HearApiClient
from src.container import ApplicationContainer
from src.database.persistence import MemoryPersistenceAdapter
from src.models.user import User
from tests.test_audio_player_runtime import USER_ID, _event

FIRST = "45f0b8df-0000-0000-0000-000000000001"
LAST = "b2b10fb9-4ede-47d4-b80d-2d00435c0071"
CONTEXT = {"kind": "organization", "name": "Northampton Sound News"}


def _item(content_id: str, title: str) -> dict:
    # The catalogue sent no duration for these recordings in production.
    return {
        "contentId": content_id,
        "title": title,
        "organizationId": "org-n",
        "organizationName": "Northampton Sound News",
        "creatorId": "creator-n",
        "creatorName": "Northampton Sound News",
        "audioUrl": f"https://cdn.hear.media/{content_id}.mp3",
    }


class Session:
    def __init__(self, monkeypatch) -> None:
        monkeypatch.setattr(
            HearApiClient,
            "resolve_listener_identity",
            AsyncMock(return_value={"listenerId": "listener-1"}),
        )
        monkeypatch.setattr(LaunchTracker, "record", lambda *_args: {"save": {}})
        for name in ("_ensure_listener_data_for_launch", "_sync_listener_for_launch"):
            monkeypatch.setattr(
                LaunchWorkflow, name, AsyncMock(side_effect=lambda _hi, store: store)
            )
        monkeypatch.setattr("src.alexa.playback_workflow.Playback.emit", AsyncMock())
        self.persistence = MemoryPersistenceAdapter()
        self.persistence._store[USER_ID] = {
            "onboardingComplete": True,
            "listenerId": "listener-1",
            "playCount": 9,
            "lastToken": LAST,
            "playbackQueue": {
                "queueId": "q1",
                "currentIndex": 1,
                "orderedContentIds": [FIRST, LAST],
                "discoveryContext": CONTEXT,
                "contentCache": {FIRST: _item(FIRST, "15_Oct5"), LAST: _item(LAST, "16_Oct5")},
            },
            "activePlayback": {
                **_item(LAST, "16_Oct5"),
                "token": LAST,
                "status": "playing",
                "offsetMs": 60000,
                "listenedMs": 60000,
                "queueId": "q1",
                "queueIndex": 1,
                "sessionId": f"{LAST}:session",
                "startedAt": 1,
                "updatedAt": 1,
                "discoveryContext": CONTEXT,
            },
        }

    async def send(self, request: dict, *, new: bool = False) -> dict:
        skill = Application.build_skill(self.persistence, container=ApplicationContainer())
        return (await skill.invoke(_event(request, new=new), None))["response"]

    async def say(self, intent: str, **slots) -> dict:
        return await self.send(
            {
                "type": "IntentRequest",
                "intent": {
                    "name": intent,
                    "confirmationStatus": "NONE",
                    "slots": {k: {"name": k, "value": v} for k, v in slots.items()},
                },
            }
        )

    async def finish_last_item(self) -> dict:
        return await self.send(
            {"type": "AudioPlayer.PlaybackFinished", "token": LAST, "offsetInMilliseconds": 81685}
        )

    def state(self) -> dict:
        key = next(key for key in reversed(list(self.persistence._store)) if key != USER_ID)
        return User.merge_persisted(dict(self.persistence._store[key]))


def _speech(response: dict) -> str:
    return (response.get("outputSpeech") or {}).get("ssml", "")


@pytest.mark.asyncio
async def test_finish_is_recorded_durably_even_without_a_catalogue_duration(monkeypatch):
    session = Session(monkeypatch)

    await session.finish_last_item()

    active = session.state()["activePlayback"]
    assert active["status"] == "completed"
    assert active["completedAt"]
    assert active["durationMs"] == 81685
    assert PlaybackState.is_finished({**active, "status": "paused"})


@pytest.mark.asyncio
async def test_play_button_after_the_queue_finished_does_not_replay_the_end(monkeypatch):
    session = Session(monkeypatch)
    await session.finish_last_item()

    response = await session.send({"type": "PlaybackController.PlayCommandIssued"})

    assert not any(
        directive.get("type") == "AudioPlayer.Play" for directive in response.get("directives") or []
    )
    assert session.state()["activePlayback"]["status"] == "completed"


@pytest.mark.asyncio
async def test_unrecognised_feedback_answers_cannot_loop(monkeypatch):
    session = Session(monkeypatch)
    await session.finish_last_item()
    assert "did you enjoy" in _speech(await session.send({"type": "LaunchRequest"}, new=True))

    retry = _speech(await session.say("AMAZON.FallbackIntent"))
    given_up = _speech(await session.say("AMAZON.FallbackIntent"))

    assert "Just say yes or no" in retry
    assert Speech.FEEDBACK_GIVEN_UP in given_up
    state = session.state()
    assert state["awaitingFeedback"] is False
    assert state["activePlayback"]["feedbackAnswered"] is True


@pytest.mark.asyncio
async def test_yes_after_an_unrecognised_answer_records_enjoyed(monkeypatch):
    session = Session(monkeypatch)
    await session.finish_last_item()
    await session.send({"type": "LaunchRequest"}, new=True)
    await session.say("AMAZON.FallbackIntent")

    assert "Glad you enjoyed it" in _speech(await session.say("AMAZON.YesIntent"))


@pytest.mark.asyncio
async def test_rated_recording_is_not_rated_again_when_finished_is_redelivered(monkeypatch):
    session = Session(monkeypatch)
    await session.finish_last_item()
    await session.send({"type": "LaunchRequest"}, new=True)
    await session.say("AMAZON.NoIntent")
    reported = _speech(await session.say("ReportContentIntent"))

    await session.finish_last_item()
    relaunch = _speech(await session.send({"type": "LaunchRequest"}, new=True))

    assert "continue listening" not in reported
    assert "keep listening" not in reported
    assert "did you enjoy" not in relaunch
    assert session.state()["awaitingFeedback"] is False
