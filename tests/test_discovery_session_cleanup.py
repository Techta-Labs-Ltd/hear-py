from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.alexa.speech import Speech
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.controllers.playback_controls import PauseIntentHandler
from src.controllers.system import CancelIntentHandler, SessionEndedHandler
from src.middleware.dialog_validation import DialogValidationPolicy
from src.models.dialog import DialogStateManager
from src.models.user import User


def _handler_input(request_type: str, intent_name: str | None = None):

    class DotDict(dict):
        def __getattr__(self, key):
            value = self.get(key)
            return DotDict(value) if isinstance(value, dict) else value

    handler_input = MagicMock()
    request = DotDict(
        {
            "type": request_type,
            "reason": "USER_INITIATED",
            "intent": {"name": intent_name},
        }
    )
    handler_input.request_envelope = DotDict(
        {
            "request": request,
            "context": {"System": {"user": {"userId": "test-user"}}},
            "session": {"user": {"userId": "test-user"}},
        }
    )
    resolution = {"confirmationLabel": "sport", "searchPayload": {"query": "sport"}}
    store = {
        **StateSchema.DEFAULT_STORE,
        "awaitingSearchConfirmation": True,
        "pendingResolution": resolution,
        "pendingAmbiguity": {"candidates": ["sport"]},
        "pendingSuggestions": [{"label": "news"}],
        "suggestionIndex": 1,
        "excludedSuggestions": ["sport"],
        "activeDialog": {"type": "search_confirmation", "context": resolution},
        "activePlayback": {"token": "keep-me"},
        "awaitingFeedback": True,
        "onboardingStage": "ask_town",
        "followedCreators": ["creator-123"],
    }
    attrs = {"_store": store, "_dirty": False}
    handler_input.attributes_manager.request_attributes = attrs
    handler_input.attributes_manager.get_request_attributes.side_effect = lambda: attrs
    handler_input.response_builder.speak.return_value = handler_input.response_builder
    handler_input.response_builder.add_directive.return_value = handler_input.response_builder
    handler_input.response_builder.response = {}
    return handler_input


def _assert_discovery_cleared(handler_input):
    store = User.snapshot(handler_input)
    assert store["awaitingSearchConfirmation"] is False
    assert store["pendingResolution"] is None
    assert store["pendingAmbiguity"] is None
    assert store["pendingSuggestions"] == []
    assert store["suggestionIndex"] == 0
    assert store["excludedSuggestions"] == []
    assert store["activeDialog"] is None
    assert store["activePlayback"] == {"token": "keep-me"}
    assert store["awaitingFeedback"] is True
    assert store["onboardingStage"] == "ask_town"
    assert store["followedCreators"] == ["creator-123"]


def test_cleanup_preserves_non_discovery_active_dialog():
    handler_input = _handler_input("LaunchRequest")
    store = User.snapshot(handler_input)
    store["activeDialog"] = {"type": "feedback", "context": {"contentId": "123"}}
    handler_input.attributes_manager.request_attributes["_store"] = store
    DialogStateManager.clear_transient_discovery(handler_input)
    assert User.snapshot(handler_input)["activeDialog"] == {
        "type": "feedback",
        "context": {"contentId": "123"},
    }


def test_new_play_request_is_not_blocked_after_cleanup():
    handler_input = _handler_input("IntentRequest", "PlayContentIntent")
    DialogStateManager.clear_transient_discovery(handler_input)
    assert DialogValidationPolicy.dialog_validation_failure(handler_input) is None


@pytest.mark.asyncio
async def test_session_ended_clears_discovery_state(monkeypatch):
    handler_input = _handler_input("SessionEndedRequest")
    deps = SimpleNamespace(playback=AsyncMock())
    await SessionEndedHandler(deps=deps).handle(handler_input)
    _assert_discovery_cleared(handler_input)


@pytest.mark.asyncio
async def test_cancel_clears_discovery_state(monkeypatch):
    handler_input = _handler_input("IntentRequest", "AMAZON.CancelIntent")
    monkeypatch.setattr("src.models.playback.Playback.emit_user", AsyncMock())
    await CancelIntentHandler(deps=ApplicationContainer()).handle(handler_input)
    _assert_discovery_cleared(handler_input)


@pytest.mark.asyncio
async def test_stop_clears_discovery_state(monkeypatch):
    handler_input = _handler_input("IntentRequest", "AMAZON.StopIntent")
    monkeypatch.setattr("src.models.playback.PlaybackState.merge", lambda *_args: {})
    monkeypatch.setattr("src.models.playback.Playback.emit", AsyncMock())
    await PauseIntentHandler(deps=ApplicationContainer()).handle(handler_input)
    _assert_discovery_cleared(handler_input)
    handler_input.response_builder.speak.assert_called_once_with(Speech.GOODBYE)


@pytest.mark.asyncio
async def test_pause_does_not_clear_discovery_state(monkeypatch):
    handler_input = _handler_input("IntentRequest", "AMAZON.PauseIntent")
    monkeypatch.setattr("src.models.playback.PlaybackState.merge", lambda *_args: {})
    monkeypatch.setattr("src.models.playback.Playback.emit", AsyncMock())
    await PauseIntentHandler(deps=ApplicationContainer()).handle(handler_input)
    assert User.snapshot(handler_input)["awaitingSearchConfirmation"] is True
    assert User.snapshot(handler_input)["pendingResolution"]["confirmationLabel"] == "sport"
