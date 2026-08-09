from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.handlers.playback import PauseIntentHandler
from src.handlers.system import CancelIntentHandler, SessionEndedHandler
from src.middleware.dialog_validation import dialog_validation_failure
from src.services.dialog_state import clear_transient_discovery_dialog
from src.services.store import DEFAULT_STORE, get_store


def _handler_input(request_type: str, intent_name: str | None = None):
    class DotDict(dict):
        def __getattr__(self, key):
            value = self.get(key)
            return DotDict(value) if isinstance(value, dict) else value

    handler_input = MagicMock()
    request = DotDict({
        "type": request_type,
        "reason": "USER_INITIATED",
        "intent": {"name": intent_name},
    })
    handler_input.request_envelope = DotDict({
        "request": request,
        "context": {"System": {"user": {"userId": "test-user"}}},
        "session": {"user": {"userId": "test-user"}},
    })

    resolution = {
        "confirmationLabel": "sport",
        "searchPayload": {"query": "sport"},
    }
    store = {
        **DEFAULT_STORE,
        "awaitingSearchConfirmation": True,
        "pendingResolution": resolution,
        "pendingAmbiguity": {"candidates": ["sport"]},
        "pendingSuggestions": [{"label": "news"}],
        "suggestionIndex": 1,
        "excludedSuggestions": ["sport"],
        "activeDialog": {
            "type": "search_confirmation",
            "context": resolution,
        },
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
    store = get_store(handler_input)
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
    store = get_store(handler_input)
    store["activeDialog"] = {"type": "feedback", "context": {"contentId": "123"}}
    handler_input.attributes_manager.request_attributes["_store"] = store

    clear_transient_discovery_dialog(handler_input)

    assert get_store(handler_input)["activeDialog"] == {
        "type": "feedback",
        "context": {"contentId": "123"},
    }


def test_new_play_request_is_not_blocked_after_cleanup():
    handler_input = _handler_input("IntentRequest", "PlayContentIntent")

    clear_transient_discovery_dialog(handler_input)

    assert dialog_validation_failure(handler_input) is None


@pytest.mark.asyncio
async def test_session_ended_clears_discovery_state(monkeypatch):
    handler_input = _handler_input("SessionEndedRequest")
    monkeypatch.setattr("src.handlers.system.flush_previous_track", AsyncMock())

    await SessionEndedHandler().handle(handler_input)

    _assert_discovery_cleared(handler_input)


@pytest.mark.asyncio
async def test_cancel_clears_discovery_state(monkeypatch):
    handler_input = _handler_input("IntentRequest", "AMAZON.CancelIntent")
    monkeypatch.setattr("src.handlers.system.emit_user_playback_event", AsyncMock())

    await CancelIntentHandler().handle(handler_input)

    _assert_discovery_cleared(handler_input)


@pytest.mark.asyncio
async def test_stop_clears_discovery_state(monkeypatch):
    handler_input = _handler_input("IntentRequest", "AMAZON.StopIntent")
    monkeypatch.setattr("src.handlers.playback.write_playback_session", lambda *_args: {})
    monkeypatch.setattr("src.handlers.playback.emit_listening_event", AsyncMock())

    await PauseIntentHandler().handle(handler_input)

    _assert_discovery_cleared(handler_input)


@pytest.mark.asyncio
async def test_pause_does_not_clear_discovery_state(monkeypatch):
    handler_input = _handler_input("IntentRequest", "AMAZON.PauseIntent")
    monkeypatch.setattr("src.handlers.playback.write_playback_session", lambda *_args: {})
    monkeypatch.setattr("src.handlers.playback.emit_listening_event", AsyncMock())

    await PauseIntentHandler().handle(handler_input)

    assert get_store(handler_input)["awaitingSearchConfirmation"] is True
    assert get_store(handler_input)["pendingResolution"]["confirmationLabel"] == "sport"
