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


THIRD = "cccccccc-0000-0000-0000-000000000003"


def _three_item_session(monkeypatch, *, heard: tuple[str, ...]) -> Session:
    session = Session(monkeypatch)
    stored = session.persistence._store[USER_ID]
    stored["playbackQueue"]["orderedContentIds"] = [FIRST, LAST, THIRD]
    stored["playbackQueue"]["currentIndex"] = 0
    stored["playbackQueue"]["contentCache"][THIRD] = _item(THIRD, "17_Oct5")
    stored["activePlayback"].update(
        {**_item(FIRST, "15_Oct5"), "token": FIRST, "queueIndex": 0, "sessionId": f"{FIRST}:s"}
    )
    stored["playHistory"] = [
        {**_item(content_id, "heard"), "completed": True, "offsetMs": 81685}
        for content_id in heard
    ]
    return session


def _played(response: dict) -> list[tuple[str, str]]:
    return [
        (directive.get("playBehavior"), directive["audioItem"]["stream"]["token"])
        for directive in response.get("directives") or []
        if directive.get("type") == "AudioPlayer.Play"
    ]


@pytest.mark.asyncio
async def test_next_skips_a_recording_the_listener_already_finished(monkeypatch):
    session = _three_item_session(monkeypatch, heard=(LAST,))

    response = await session.say("AMAZON.NextIntent")

    assert _played(response) == [("REPLACE_ALL", THIRD)]


@pytest.mark.asyncio
async def test_automatic_advance_skips_a_recording_the_listener_already_finished(monkeypatch):
    session = _three_item_session(monkeypatch, heard=(LAST,))

    response = await session.send(
        {"type": "AudioPlayer.PlaybackNearlyFinished", "token": FIRST, "offsetInMilliseconds": 70000}
    )

    assert _played(response) == [("ENQUEUE", THIRD)]


@pytest.mark.asyncio
async def test_next_keeps_queue_order_when_everything_left_was_heard(monkeypatch):
    session = _three_item_session(monkeypatch, heard=(LAST, THIRD))

    response = await session.say("AMAZON.NextIntent")

    assert _played(response) == [("REPLACE_ALL", LAST)]


@pytest.mark.asyncio
async def test_replaying_a_fully_heard_source_still_plays_the_whole_queue(monkeypatch):
    session = _three_item_session(monkeypatch, heard=(FIRST, LAST, THIRD))

    response = await session.send(
        {"type": "AudioPlayer.PlaybackNearlyFinished", "token": FIRST, "offsetInMilliseconds": 7000}
    )

    assert _played(response) == [("ENQUEUE", LAST)]


@pytest.mark.asyncio
async def test_previous_still_returns_to_a_finished_recording(monkeypatch):
    session = _three_item_session(monkeypatch, heard=(FIRST,))
    stored = session.persistence._store[USER_ID]
    stored["playbackQueue"]["currentIndex"] = 1
    stored["activePlayback"].update(
        {**_item(LAST, "16_Oct5"), "token": LAST, "queueIndex": 1, "sessionId": f"{LAST}:s"}
    )

    response = await session.say("AMAZON.PreviousIntent")

    assert _played(response) == [("REPLACE_ALL", FIRST)]


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("I enjoyed", "enjoyed"),
        ("I enjoy it", "enjoyed"),
        ("and joyed it", "enjoyed"),
        ("I love it", "enjoyed"),
        ("great", "enjoyed"),
        ("not really", "not enjoyed"),
        ("not good", "not enjoyed"),
        ("I don't like it", "not enjoyed"),
        ("it was bad", "not enjoyed"),
        ("not bad", "somewhat"),
        ("ok", "somewhat"),
        ("play York Talking News", None),
    ],
)
def test_feedback_answers_are_understood_in_the_listeners_own_words(spoken, expected):
    from src.alexa.feedback import AlexaFeedback

    assert AlexaFeedback.normalize_value(spoken) == expected


@pytest.mark.asyncio
async def test_unmatched_feedback_response_retries_once_then_moves_on(monkeypatch):
    session = Session(monkeypatch)
    await session.finish_last_item()
    await session.send({"type": "LaunchRequest"}, new=True)

    retry = _speech(await session.say("FeedbackResponseIntent", feedback="mmm hmm"))
    given_up = _speech(await session.say("FeedbackResponseIntent", feedback="blah"))

    assert "Just say yes or no" in retry
    assert Speech.FEEDBACK_GIVEN_UP in given_up
    assert session.state()["awaitingFeedback"] is False


@pytest.mark.asyncio
async def test_feedback_prompt_offers_i_enjoyed(monkeypatch):
    session = Session(monkeypatch)
    await session.finish_last_item()

    prompt = _speech(await session.send({"type": "LaunchRequest"}, new=True))

    assert 'I enjoyed, <break time="250ms"/>it was okay' in prompt
