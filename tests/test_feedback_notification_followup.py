from unittest.mock import AsyncMock

import pytest

from src.alexa.launch import LaunchWorkflow
from src.alexa.onboarding import LaunchTracker
from src.alexa.phrase_router import PhraseRouter
from src.alexa.speech import Speech
from src.application import Application
from src.clients.hear import HearApiClient
from src.container import ApplicationContainer
from src.database.persistence import MemoryPersistenceAdapter
from tests.test_audio_player_runtime import CONTENT_ID, USER_ID, _event, _playback_state
from tests.test_notifications import FakeHearApi, NotificationExamples


async def _answer_feedback_with_pending_notification(monkeypatch, intent: dict) -> tuple[str, list]:
    item = NotificationExamples.creator()
    hear = FakeHearApi(items=[item])
    hear.pending = AsyncMock(return_value={"items": [item], "failed": False})
    monkeypatch.setattr(
        HearApiClient,
        "resolve_listener_identity",
        AsyncMock(return_value={"listenerId": "listener-1"}),
    )
    monkeypatch.setattr(LaunchTracker, "record", lambda *_args: {"save": {}})
    monkeypatch.setattr(
        LaunchWorkflow,
        "_ensure_listener_data_for_launch",
        AsyncMock(side_effect=lambda _handler_input, store: store),
    )
    monkeypatch.setattr(
        LaunchWorkflow,
        "_sync_listener_for_launch",
        AsyncMock(side_effect=lambda _handler_input, store: store),
    )
    monkeypatch.setattr("src.alexa.playback_workflow.Playback.emit", AsyncMock())
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "listenerId": "listener-1",
        "playCount": 3,
        "lastToken": CONTENT_ID,
        "activePlayback": _playback_state(status="playing", offset_ms=170000),
    }

    async def invoke(request: dict, *, new: bool = False) -> str:
        skill = Application.build_skill(
            persistence, container=ApplicationContainer(notification_api=hear)
        )
        response = await skill.invoke(_event(request, new=new), None)
        return (response["response"].get("outputSpeech") or {}).get("ssml", "")

    await invoke(
        {
            "type": "AudioPlayer.PlaybackFinished",
            "token": CONTENT_ID,
            "offsetInMilliseconds": 180000,
        }
    )
    launch = await invoke({"type": "LaunchRequest"}, new=True)
    assert "did you enjoy" in launch
    answer = await invoke(
        {"type": "IntentRequest", "intent": {"confirmationStatus": "NONE", **intent}}
    )
    return answer, hear.statuses


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "acknowledgement"),
    [
        ({"name": "FeedbackSomewhatIntent", "slots": {}}, Speech.FEEDBACK_SOMEWHAT_ACK),
        ({"name": "SkipFeedbackIntent", "slots": {}}, "Ok."),
    ],
)
async def test_followup_notification_keeps_the_feedback_acknowledgement(
    monkeypatch, intent, acknowledgement
):
    spoken, statuses = await _answer_feedback_with_pending_notification(monkeypatch, intent)

    assert f"{acknowledgement} Good news, you've got a new release from Pendle Voice." in spoken
    assert statuses == [("listener-1", "notification-1", "offered")]


@pytest.mark.asyncio
async def test_feedback_answer_misrouted_to_a_slot_only_intent_is_recovered(monkeypatch):
    spoken, _ = await _answer_feedback_with_pending_notification(
        monkeypatch,
        {
            "name": "CarrierlessDiscoveryIntent",
            "slots": {"topic": {"name": "topic", "value": "I enjoyed it"}},
        },
    )

    assert "Glad you enjoyed it" in spoken


@pytest.mark.parametrize(
    "phrase", ["I enjoyed it", "it was ok", "I didn't enjoy it", "I did not enjoy it"]
)
def test_feedback_phrases_route_to_the_feedback_response(phrase):
    route = PhraseRouter.feedback_route(phrase)

    assert route is not None
    assert route.intent_name == "FeedbackResponseIntent"
    assert route.slot_map() == {"feedback": {"name": "feedback", "value": phrase}}


@pytest.mark.parametrize("phrase", ["play York Talking News", "news in Leeds", "enjoyed it all"])
def test_non_feedback_phrases_are_not_taken_as_feedback(phrase):
    assert PhraseRouter.feedback_route(phrase) is None


def test_feedback_options_are_spoken_as_separate_answers():
    assert Speech.FEEDBACK_OPTIONS.count('<break time="250ms"/>') == 3
    assert "Say I enjoyed it" not in Speech.FEEDBACK_AWAITING_REPROMPT
