from unittest.mock import AsyncMock

import pytest

from src.alexa.context import RequestContext
from src.alexa.feedback_response import FeedbackContinuation, SomewhatFeedback
from src.alexa.feedback_service import FeedbackService
from src.alexa.playback_state import PlaybackState
from src.application import Application
from src.container import ApplicationContainer
from src.database.persistence import MemoryPersistenceAdapter
from src.models.confirmation import ConfirmationPolicy
from src.models.resolver import ResolverResult
from src.models.user import User
from tests.test_audio_player_runtime import (
    CONTENT_ID,
    SECOND_CONTENT_ID,
    USER_ID,
    _event,
    _playback_state,
)


def test_empty_resolver_search_clarifies_instead_of_confirming_raw_utterance():
    result = ResolverResult.from_payload(
        {
            "status": "resolved",
            "intent": "search",
            "entities": [],
            "slots": {
                "residualQuery": "",
                "latest": False,
                "isRecommended": False,
                "isPublication": False,
                "publishedFrom": None,
                "publishedTo": None,
            },
            "ambiguities": [],
            "timingMs": 1.7,
        }
    ).to_alexa_payload(original_utterance="find me contents from")
    decision = ConfirmationPolicy.decide(
        result,
        request_type="IntentRequest",
        alexa_intent="SearchContentIntent",
        raw_utterance="find me contents from",
        validation_failed=False,
    )
    assert result["searchPayload"]["query"] == ""
    assert decision.kind == "clarify"
    assert "Sorry, I didn't catch that" in decision.clarification["speech"]


@pytest.mark.parametrize("kind", ["publication", "organization"])
def test_completed_final_track_does_not_offer_continuation_with_stale_queue_index(kind):
    store = {
        "activePlayback": {"contentId": SECOND_CONTENT_ID, "status": "completed", "queueId": "q"},
        "playbackQueue": {
            "queueId": "q",
            "currentIndex": 0,
            "orderedContentIds": [CONTENT_ID, SECOND_CONTENT_ID],
        },
    }
    assert (
        FeedbackContinuation._context(
            {"discoveryContext": {"kind": kind, "name": "Weekly news"}}, store
        )
        is None
    )


def test_at_end_paused_recording_is_not_unfinished():
    assert not PlaybackState(User()).has_unfinished(
        {"activePlayback": _playback_state(offset_ms=180000)}
    )


@pytest.mark.asyncio
async def test_stop_after_completion_cannot_resurrect_playback(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": _playback_state(status="completed", offset_ms=180000),
    }
    monkeypatch.setattr("src.alexa.playback_workflow.Playback.emit", AsyncMock())
    await Application.build_skill(persistence, container=ApplicationContainer()).invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackStopped",
                "token": CONTENT_ID,
                "offsetInMilliseconds": 180000,
            }
        ),
        None,
    )
    assert persistence._store[USER_ID]["activePlayback"]["status"] == "completed"


def test_feedback_expires_after_thirty_minutes(monkeypatch, mock_handler_input):
    from src.alexa.dialog import DialogStateManager

    monkeypatch.setattr("src.alexa.dialog.time.time", lambda: 1000)
    User.update(mock_handler_input, {"pendingFeedback": {"feedbackKey": "x"}})
    DialogStateManager.activate(mock_handler_input, "feedback", context={"feedbackKey": "x"})
    store = User.snapshot(mock_handler_input)
    assert store["activeDialog"]["expiresAt"] == 2800
    monkeypatch.setattr("src.alexa.dialog.time.time", lambda: 2799)
    assert User.merge_persisted(store)["awaitingFeedback"]
    monkeypatch.setattr("src.alexa.dialog.time.time", lambda: 2801)
    hydrated = User.merge_persisted(store)
    assert not hydrated["awaitingFeedback"]
    assert hydrated["pendingFeedback"] is None


@pytest.mark.asyncio
async def test_rating_completed_recording_does_not_restart_it(mock_handler_input):
    User.update(
        mock_handler_input,
        {
            "awaitingFeedback": True,
            "pendingFeedback": {
                "feedbackKey": CONTENT_ID,
                "contentId": CONTENT_ID,
                "completed": True,
                "requested": True,
            },
            "activePlayback": _playback_state(status="completed", offset_ms=180000),
        },
    )
    controls = AsyncMock()
    await SomewhatFeedback(FeedbackService(), controls, User()).execute(
        RequestContext.bind(mock_handler_input)
    )
    controls.restart_active.assert_not_awaited()
    assert not User.snapshot(mock_handler_input)["awaitingFeedbackContinuation"]


@pytest.mark.asyncio
async def test_finished_event_corrects_stale_final_queue_position(monkeypatch):
    persistence = MemoryPersistenceAdapter()
    persistence._store[USER_ID] = {
        "onboardingComplete": True,
        "activePlayback": {**_playback_state(status="playing", offset_ms=179000), "queueId": "q"},
        "playbackQueue": {
            "queueId": "q",
            "currentIndex": 0,
            "orderedContentIds": [SECOND_CONTENT_ID, CONTENT_ID],
        },
    }
    monkeypatch.setattr("src.alexa.playback_workflow.Playback.emit", AsyncMock())
    await Application.build_skill(persistence, container=ApplicationContainer()).invoke(
        _event(
            {
                "type": "AudioPlayer.PlaybackFinished",
                "token": CONTENT_ID,
                "offsetInMilliseconds": 180000,
            }
        ),
        None,
    )
    store = persistence._store[USER_ID]
    assert store["playbackQueue"]["currentIndex"] == 1
    assert store["activePlayback"]["status"] == "completed"
