from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, Optional

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from config.permission_scopes import DEVICE_ADDRESS, GEOLOCATION_READ

from src.services.storage.persistence import get_store, update_store
from src.services.dialog_state import activate_dialog
from src.services.alexa.locality import detect_device_location
from src.services.resolver_client import ResolverUnavailable, resolve_utterance
from src.nlp.patterns import BROWSE_HINTS, FEEDBACK_SKIP_HINTS, LOCAL_HINTS, TRENDING_HINTS
from src.utils.skill_request import get_request_type
from src.utils.normalize_content_item import pick_content_source
from src.utils.speech import (
    ssml, ONBOARDING_ASK_PERMISSION, ONBOARDING_CONSENT_CARD_SENT,
    ONBOARDING_LOCATION_DENIED, WELCOME_FIRST_ASK_TOWN, REPROMPT_ASK_TOWN,
    TOWN_NOT_UNDERSTOOD, TOWN_GOT_IT, REPROMPT_CITY, TOWN_SKIPPED, REPROMPT_NO_CITY,
    TOWN_LOOKUP_UNAVAILABLE_RETRY, TOWN_LOOKUP_UNAVAILABLE_CONTINUE,
    WELCOME_RETURN_NAMED, WELCOME_RETURN_CITY, WELCOME_RETURN_GENERIC,
    ONBOARDING_TOWN_CONFIRM, ONBOARDING_FETCHING_LOCATION,
    ONBOARDING_DETECTED_TOWN, CONSENT_CARD_THANKS, LOCATION_DECLINED,
    ONBOARDING_DEFER_CONTENT, LOCATION_NOT_FOUND,
    LATEST_SOURCE_OFFER, LATEST_SOURCE_REPROMPT,
)
ONBOARDING_ASK_TOWN = "ask_town"
ONBOARDING_AWAIT_CONFIRM = "await_location_confirm"
MAX_TOWN_ATTEMPTS = 3
MAX_TOWN_RESOLVER_FAILURES = 2
PERMISSIONS = {"DEVICE_ADDRESS": DEVICE_ADDRESS, "GEOLOCATION": GEOLOCATION_READ}
logger = logging.getLogger(__name__)

TOWN_CONFIRM_REPROMPT = "Say yes to confirm, or no to set a different town."


def _normalize_control_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


TOWN_SKIP_PHRASES = frozenset(
    _normalize_control_phrase(value) for value in FEEDBACK_SKIP_HINTS
)
CONTENT_REQUEST_PHRASES = frozenset(
    _normalize_control_phrase(value)
    for value in BROWSE_HINTS | LOCAL_HINTS | TRENDING_HINTS
)

def onboarding_pending_redirect(handler_input: HandlerInput, store: Dict[str, Any]):
    stage = store.get("onboardingStage")
    if stage == ONBOARDING_ASK_TOWN:
        return resume_town_capture(handler_input, store)
    if stage == ONBOARDING_AWAIT_CONFIRM:
        pending = store.get("pendingLocationConfirm") or {}
        city = pending.get("city")
        if not city:
            return None
        return handler_input.response_builder \
            .speak(ssml(ONBOARDING_TOWN_CONFIRM(city))) \
            .reprompt(ssml(TOWN_CONFIRM_REPROMPT)) \
            .set_should_end_session(False) \
            .response
    return None


def ask_for_permission(handler_input: HandlerInput, store: Dict[str, Any]):
    """Prompt the user to grant device-address and geolocation permissions."""
    update_store(handler_input, {
        "onboardingStage": "ask_permission",
        "_requiresReliableSave": True,
    })
    handler_input.attributes_manager.set_session_attributes({
        "onboardingStage": "ask_permission",
    })
    return handler_input.response_builder \
        .speak(ssml(ONBOARDING_ASK_PERMISSION)) \
        .set_should_end_session(False) \
        .response


def handle_permission_yes(handler_input: HandlerInput, store: Dict[str, Any]):
    """Handle user consent — send a permissions consent card."""
    permissions = [PERMISSIONS["DEVICE_ADDRESS"], PERMISSIONS["GEOLOCATION"]]
    update_store(handler_input, {"onboardingStage": "ask_permission"})
    return handler_input.response_builder \
        .speak(ssml(ONBOARDING_CONSENT_CARD_SENT)) \
        .with_ask_for_permissions_consent_card(permissions) \
        .set_should_end_session(False) \
        .response


def handle_permission_no(handler_input: HandlerInput, store: Dict[str, Any]):
    """Handle permission denial — fall back to manual town entry."""
    update_store(handler_input, {
        "onboardingStage": ONBOARDING_ASK_TOWN,
        "onboardingRetries": 0,
        "_requiresReliableSave": True,
    })
    handler_input.attributes_manager.set_session_attributes({
        "onboardingStage": ONBOARDING_ASK_TOWN,
    })
    return handler_input.response_builder \
        .speak(ssml(ONBOARDING_LOCATION_DENIED)) \
        .reprompt(ssml(REPROMPT_ASK_TOWN)) \
        .set_should_end_session(False) \
        .response


def handle_returning_user(
    handler_input: HandlerInput,
    store: Dict[str, Any],
    resolved_user_name: Optional[str],
    resolved_locality: Optional[str],
):
    source = store.get("lastCompletedSource")
    if isinstance(source, dict):
        content_id = source.get("contentId")
        selected_source = pick_content_source(source)
        source_name = source.get("sourceName") or (selected_source or {}).get("name")
        source_id = source.get("sourceId") or (selected_source or {}).get("id")
        if source_name and source_id and content_id != store.get("lastLatestSourceOfferContentId"):
            update_store(handler_input, {
                "pendingLatestSource": source,
                "lastLatestSourceOfferContentId": content_id,
            })
            activate_dialog(handler_input, "latest_source", context=source)
            return handler_input.response_builder \
                .speak(ssml(LATEST_SOURCE_OFFER(source_name))) \
                .reprompt(ssml(LATEST_SOURCE_REPROMPT(source_name))) \
                .set_should_end_session(False) \
                .response
    city = store.get("userCity") or resolved_locality
    if resolved_user_name and city:
        return handler_input.response_builder \
            .speak(ssml(WELCOME_RETURN_NAMED(resolved_user_name, city))) \
            .set_should_end_session(False) \
            .response
    if city:
        return handler_input.response_builder \
            .speak(ssml(WELCOME_RETURN_CITY(city))) \
            .set_should_end_session(False) \
            .response
    return handler_input.response_builder \
        .speak(ssml(WELCOME_RETURN_GENERIC)) \
        .set_should_end_session(False) \
        .response


def start_town_capture(handler_input: HandlerInput, store: Dict[str, Any], name: Optional[str]):
    """Begin the town-capture flow asking where the user is based."""
    update_store(handler_input, {
        "onboardingStage": ONBOARDING_ASK_TOWN,
        "onboardingTownAttempts": 0,
        "onboardingTownResolverFailures": 0,
    })
    handler_input.attributes_manager.set_session_attributes({
        "onboardingStage": ONBOARDING_ASK_TOWN,
    })
    return handler_input.response_builder \
        .speak(ssml(WELCOME_FIRST_ASK_TOWN(name))) \
        .reprompt(ssml(REPROMPT_ASK_TOWN)) \
        .set_should_end_session(False) \
        .response


def resume_town_capture(handler_input: HandlerInput, store: Dict[str, Any]):
    """Retry or give up on town capture based on attempt count."""
    attempts = store.get("onboardingTownAttempts", 0)
    if attempts >= MAX_TOWN_ATTEMPTS:
        return finalize_town_skipped(handler_input, store)
    update_store(handler_input, {"onboardingTownAttempts": attempts + 1})
    return handler_input.response_builder \
        .speak(ssml(TOWN_NOT_UNDERSTOOD)) \
        .reprompt(ssml(REPROMPT_ASK_TOWN)) \
        .set_should_end_session(False) \
        .response


def handle_town_resolver_unavailable(handler_input: HandlerInput, store: Dict[str, Any]):
    """Keep one retry in-session, then finish onboarding without location."""
    failures = int(store.get("onboardingTownResolverFailures") or 0) + 1
    if failures < MAX_TOWN_RESOLVER_FAILURES:
        update_store(handler_input, {
            "onboardingStage": ONBOARDING_ASK_TOWN,
            "onboardingTownResolverFailures": failures,
        })
        return handler_input.response_builder \
            .speak(ssml(TOWN_LOOKUP_UNAVAILABLE_RETRY)) \
            .reprompt(ssml(REPROMPT_ASK_TOWN)) \
            .set_should_end_session(False) \
            .response

    update_store(handler_input, {
        "onboardingStage": None,
        "onboardingTownAttempts": 0,
        "onboardingTownResolverFailures": 0,
        "onboardingComplete": True,
        "awaitingLocationConfirm": False,
        "pendingLocationConfirm": None,
    })
    return handler_input.response_builder \
        .speak(ssml(TOWN_LOOKUP_UNAVAILABLE_CONTINUE)) \
        .reprompt(ssml(REPROMPT_NO_CITY)) \
        .set_should_end_session(False) \
        .response


async def stage_town_confirmation(handler_input: HandlerInput, store: Dict[str, Any], phrase: str):
    """Resolve a manual town in location scope and ask for confirmation."""
    try:
        response = await resolve_utterance(
            "resolve_location",
            phrase,
            alexa_intent="TownCaptureIntent",
        )
        resolution = response.get("resolution") or {}
    except ResolverUnavailable:
        return handle_town_resolver_unavailable(handler_input, store)
    update_store(handler_input, {"onboardingTownResolverFailures": 0})
    match = resolution.get("match")
    candidates = resolution.get("candidates") or []
    if not match:
        if candidates:
            names = [candidate["city"] for candidate in candidates[:2]]
            spoken = " or ".join(names)
            update_store(handler_input, {
                "onboardingTownAttempts": store.get("onboardingTownAttempts", 0) + 1,
            })
            return handler_input.response_builder \
                .speak(ssml(f"Did you mean {spoken}? Please say the full town name.")) \
                .reprompt(ssml(REPROMPT_ASK_TOWN)) \
                .set_should_end_session(False) \
                .response
        normalized_phrase = _normalize_control_phrase(phrase)
        if normalized_phrase in TOWN_SKIP_PHRASES:
            return finalize_town_skipped(handler_input, store)
        if normalized_phrase in CONTENT_REQUEST_PHRASES:
            update_store(handler_input, {
                "onboardingTownAttempts": store.get("onboardingTownAttempts", 0) + 1,
            })
            return handler_input.response_builder \
                .speak(ssml(ONBOARDING_DEFER_CONTENT)) \
                .reprompt(ssml(REPROMPT_ASK_TOWN)) \
                .set_should_end_session(False) \
                .response
        return resume_town_capture(handler_input, store)
    update_store(handler_input, {
        "pendingLocationConfirm": match,
        "awaitingLocationConfirm": True,
        "onboardingStage": ONBOARDING_AWAIT_CONFIRM,
    })
    return handler_input.response_builder \
        .speak(ssml(ONBOARDING_TOWN_CONFIRM(match["city"]))) \
        .reprompt(ssml(TOWN_CONFIRM_REPROMPT)) \
        .set_should_end_session(False) \
        .response


async def finalize_town_captured(
    handler_input: HandlerInput,
    store: Dict[str, Any],
    phrase: str,
):
    """Persist a resolved manual town.

    Kept as a small compatibility entry point for callers that already have an
    explicit town confirmation. New voice flows stage and confirm first.
    """
    try:
        response = await resolve_utterance(
            "resolve_location",
            phrase,
            alexa_intent="TownCaptureIntent",
        )
        resolution = response.get("resolution") or {}
    except ResolverUnavailable:
        return handle_town_resolver_unavailable(handler_input, store)
    update_store(handler_input, {"onboardingTownResolverFailures": 0})
    match = resolution.get("match")
    if not match:
        return await stage_town_confirmation(handler_input, store, phrase)
    update_store(handler_input, {
        "userCity": match["city"],
        "locality": match.get("locality") or match["city"],
        "deviceCountryCode": match.get("countryCode"),
        "latitude": match.get("latitude"),
        "longitude": match.get("longitude"),
        "onboardingComplete": True,
        "onboardingStage": None,
        "onboardingTownAttempts": 0,
        "onboardingTownResolverFailures": 0,
        "locationSource": "manual",
        "localityResolvedAt": int(time.time() * 1000),
        "awaitingLocationConfirm": False,
        "pendingLocationConfirm": None,
    })
    return handler_input.response_builder \
        .speak(ssml(TOWN_GOT_IT(match["city"]))) \
        .reprompt(ssml(REPROMPT_CITY)) \
        .set_should_end_session(False) \
        .response


def finalize_town_skipped(handler_input: HandlerInput, store: Dict[str, Any]):
    """Skip town capture and proceed without location."""
    update_store(handler_input, {
        "onboardingStage": None,
        "onboardingTownAttempts": 0,
        "onboardingTownResolverFailures": 0,
        "onboardingComplete": True,
    })

    logger.info("Hear: onboarding town skipped")

    return handler_input.response_builder \
        .speak(ssml(TOWN_SKIPPED)) \
        .reprompt(ssml(REPROMPT_NO_CITY)) \
        .set_should_end_session(False) \
        .response


def handle_location_not_found(handler_input: HandlerInput, store: Dict[str, Any]):
    """Handle device location lookup failure when permissions are granted."""
    update_store(handler_input, {
        "onboardingStage": ONBOARDING_ASK_TOWN,
        "onboardingRetries": 0,
        "onboardingTownResolverFailures": 0,
        "_requiresReliableSave": True,
    })
    handler_input.attributes_manager.set_session_attributes({
        "onboardingStage": ONBOARDING_ASK_TOWN,
    })
    return handler_input.response_builder \
        .speak(ssml(LOCATION_NOT_FOUND)) \
        .reprompt(ssml(REPROMPT_ASK_TOWN)) \
        .set_should_end_session(False) \
        .response


async def auto_detect_location_or_manual(handler_input: HandlerInput, store: Dict[str, Any]):
    """Try Amazon-API city detection; fall back to manual town capture."""
    match = await detect_device_location(handler_input)
    if not match:
        return handle_location_not_found(handler_input, store)
    update_store(handler_input, {
        "pendingLocationConfirm": match,
        "awaitingLocationConfirm": True,
        "onboardingStage": ONBOARDING_AWAIT_CONFIRM,
        "onboardingTownAttempts": 0,
    })
    return handler_input.response_builder \
        .speak(ssml(
            f"{ONBOARDING_FETCHING_LOCATION} {ONBOARDING_DETECTED_TOWN(match['city'])}"
        )) \
        .reprompt(ssml(TOWN_CONFIRM_REPROMPT)) \
        .set_should_end_session(False) \
        .response


def _consent_status_code(handler_input) -> str:
    try:
        request = handler_input.request_envelope.request
        return str((getattr(request, "status", None) or {}).get("code") or "")
    except Exception:
        return ""


class ConnectionsResponseHandler(AbstractRequestHandler):
    """Handles the in-session response to the AskForPermissionsConsent card."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return get_request_type(handler_input) == "Connections.Response"

    async def handle(self, handler_input: HandlerInput):
        store = get_store(handler_input)
        granted = _consent_status_code(handler_input).startswith("2")
        if store.get("onboardingComplete"):
            return handler_input.response_builder \
                .speak(ssml(CONSENT_CARD_THANKS if granted else LOCATION_DECLINED)) \
                .set_should_end_session(False) \
                .response
        if granted:
            return await auto_detect_location_or_manual(handler_input, store)
        return handle_permission_no(handler_input, store)
