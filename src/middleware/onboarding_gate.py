from __future__ import annotations

from typing import Any, Dict

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.services.storage.persistence import get_store
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import ssml
from src.handlers.intents.onboarding import (
    ask_for_permission, handle_permission_yes, handle_permission_no,
)


def _is_new_user(store: Dict[str, Any]) -> bool:
    """Check if the user is new (no completed onboarding, no prior playback)."""
    if store.get("onboardingComplete"):
        return False
    return store.get("playCount", 0) == 0 and not store.get("lastToken")


def _get_stage(handler_input: HandlerInput) -> str | None:
    """Resolve the current onboarding stage from store or session attributes."""
    store = get_store(handler_input)
    stage = store.get("onboardingStage")
    if not stage:
        sess = handler_input.attributes_manager.get_session_attributes() or {}
        stage = sess.get("onboardingStage")
    return stage or None


class OnboardingGateHandler(AbstractRequestHandler):
    """Gate handler that routes new users through onboarding before any content handlers."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        rt = get_request_type(handler_input)
        if rt == "LaunchRequest":
            store = get_store(handler_input)
            return _is_new_user(store)

        if isinstance(rt, str) and rt.startswith("AudioPlayer."):
            return False
        if rt == "SessionEndedRequest":
            return False
        if rt != "IntentRequest":
            return False

        store = get_store(handler_input)
        if not _is_new_user(store):
            return False

        intent = get_intent_name(handler_input)
        if intent in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
            return False

        stage = _get_stage(handler_input)
        return stage == "ask_permission" or not stage

    def handle(self, handler_input: HandlerInput):
        rt = get_request_type(handler_input)
        if rt == "LaunchRequest":
            return ask_for_permission(handler_input, get_store(handler_input))

        intent = get_intent_name(handler_input)
        stage = _get_stage(handler_input)
        store = get_store(handler_input)

        if stage == "ask_permission" or not stage:
            if intent == "AMAZON.YesIntent":
                return handle_permission_yes(handler_input, store)
            if intent == "AMAZON.NoIntent":
                return handle_permission_no(handler_input, store)
            return handler_input.response_builder \
                .speak(ssml(
                    "Just say yes to share your location, or no to tell me your town instead."
                )) \
                .set_should_end_session(False) \
                .response

        return None
