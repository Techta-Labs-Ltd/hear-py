from __future__ import annotations

import logging
from typing import Any, Dict

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from config.permission_scopes import DEVICE_ADDRESS, GEOLOCATION_READ

from src.clients.alexa_locality import has_permission

from src.services.store import get_store

from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import (
    ssml, ONBOARDING_TOWN_CONFIRM,
)
from src.handlers.onboarding import (
    ONBOARDING_ASK_TOWN,
    ONBOARDING_AWAIT_CONFIRM,
    TOWN_CONFIRM_REPROMPT,
    ask_for_permission,
    handle_permission_yes,
    handle_permission_no,
    auto_detect_location_or_manual,
    resume_town_capture,
)


logger = logging.getLogger(__name__)

# Intents that own the current onboarding stage. The gate must NOT claim
# these so their handlers keep resolving the in-flight flow.
_ASK_TOWN_OWNED_INTENTS = frozenset({
    "TownCaptureIntent", "SetLocationIntent",
    "AMAZON.NoIntent", "SkipFeedbackIntent",
})
_AWAIT_CONFIRM_OWNED_INTENTS = frozenset({
    "AMAZON.YesIntent", "AMAZON.NoIntent",
    "TownCaptureIntent", "SetLocationIntent",
})
_NLP_OWNED_INTENTS = frozenset({"town_capture", "location_set"})


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


def _location_scopes_granted(handler_input: HandlerInput) -> bool:
    """Whether the user already granted a device location scope."""
    return has_permission(handler_input, DEVICE_ADDRESS) or has_permission(
        handler_input, GEOLOCATION_READ
    )


def _confirm_echo(handler_input: HandlerInput, store: Dict[str, Any]):
    """Re-ask the location confirmation using the pending candidate city."""
    pending = store.get("pendingLocationConfirm") or {}
    city = pending.get("city")
    if not city:
        return None
    return handler_input.response_builder \
        .speak(ssml(ONBOARDING_TOWN_CONFIRM(city))) \
        .reprompt(ssml(TOWN_CONFIRM_REPROMPT)) \
        .set_should_end_session(False) \
        .response


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
        if stage in (ONBOARDING_ASK_TOWN, ONBOARDING_AWAIT_CONFIRM):
            attrs = handler_input.attributes_manager.get_request_attributes()
            nlp = attrs.get("_nlp", {}) if attrs else {}
            if nlp.get("intent") in _NLP_OWNED_INTENTS:
                return False
            owned = (
                _ASK_TOWN_OWNED_INTENTS if stage == ONBOARDING_ASK_TOWN
                else _AWAIT_CONFIRM_OWNED_INTENTS
            )
            return intent not in owned

        return stage == "ask_permission" or not stage

    async def handle(self, handler_input: HandlerInput):
        rt = get_request_type(handler_input)
        if rt == "LaunchRequest":
            store = get_store(handler_input)
            return ask_for_permission(handler_input, store)

        intent = get_intent_name(handler_input)
        stage = _get_stage(handler_input)
        store = get_store(handler_input)

        if stage == ONBOARDING_ASK_TOWN:
            logger.info(
                "Hear: town reply was not captured intent=%s; asking again",
                intent,
            )
            return resume_town_capture(handler_input, store)
        if stage == ONBOARDING_AWAIT_CONFIRM:
            redirect = _confirm_echo(handler_input, store)
            if redirect is not None:
                return redirect

        if stage == "ask_permission" or not stage:
            if intent == "AMAZON.YesIntent":
                if _location_scopes_granted(handler_input):
                    return await auto_detect_location_or_manual(handler_input, store)
                return handle_permission_yes(handler_input, store)
            if intent == "AMAZON.NoIntent":
                return handle_permission_no(handler_input, store)

        return handler_input.response_builder \
            .speak(ssml(
                "Just say yes to share your location, or no to tell me your town instead."
            )) \
            .set_should_end_session(False) \
            .response
