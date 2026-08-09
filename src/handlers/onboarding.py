from __future__ import annotations
import logging
import re
import time
from typing import Any, Dict, Optional
from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from config.permission_scopes import DEVICE_ADDRESS, GEOLOCATION_READ
from src.services.store import get_store, update_store
from src.services.dialog_state import activate_dialog, clear_active_dialog
from src.clients.resolver import ResolverUnavailable
from src.dependencies import Dependencies
from src.models import BROWSE_HINTS, FEEDBACK_SKIP_HINTS, LOCAL_HINTS, TRENDING_HINTS
from src.utils.skill_request import get_intent_name, get_request_type, get_user_id
from src.utils.normalize_content_item import pick_content_source
from src.utils.speech import (
    ssml,
    ONBOARDING_ASK_PERMISSION,
    ONBOARDING_CONSENT_CARD_SENT,
    ONBOARDING_LOCATION_DENIED,
    WELCOME_FIRST_ASK_TOWN,
    REPROMPT_ASK_TOWN,
    TOWN_NOT_UNDERSTOOD,
    TOWN_GOT_IT,
    REPROMPT_CITY,
    TOWN_SKIPPED,
    REPROMPT_NO_CITY,
    TOWN_LOOKUP_UNAVAILABLE_RETRY,
    TOWN_LOOKUP_UNAVAILABLE_CONTINUE,
    CITY_SETUP_GUIDANCE,
    WELCOME_RETURN_NAMED,
    WELCOME_RETURN_CITY,
    WELCOME_RETURN_GENERIC,
    ONBOARDING_TOWN_CONFIRM,
    ONBOARDING_DEVICE_TOWN_CONFIRM,
    CONSENT_CARD_THANKS,
    LOCATION_DECLINED,
    ONBOARDING_DEFER_CONTENT,
    LOCATION_NOT_FOUND,
    LATEST_SOURCE_OFFER,
    LATEST_SOURCE_REPROMPT,
)
ONBOARDING_ASK_TOWN = "ask_town"


ONBOARDING_AWAIT_CONFIRM = "await_location_confirm"


MAX_TOWN_ATTEMPTS = 3


MAX_TOWN_RESOLVER_FAILURES = 2


PERMISSIONS = {"DEVICE_ADDRESS": DEVICE_ADDRESS, "GEOLOCATION": GEOLOCATION_READ}


logger = logging.getLogger(__name__)


TOWN_CONFIRM_REPROMPT = "Say yes to confirm, or no to set a different city."


def _update_onboarding_session(handler_input: HandlerInput, **updates: Any) -> None:
    """Mirror turn-critical onboarding state into the active Alexa session."""
    attributes = dict(
        handler_input.attributes_manager.get_session_attributes() or {}
    )
    attributes.update(updates)
    handler_input.attributes_manager.set_session_attributes(attributes)


def _normalize_control_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


TOWN_SKIP_PHRASES = frozenset(
    _normalize_control_phrase(value) for value in FEEDBACK_SKIP_HINTS
)


CONTENT_REQUEST_PHRASES = frozenset(
    _normalize_control_phrase(value)
    for value in BROWSE_HINTS | LOCAL_HINTS | TRENDING_HINTS
)


def _town_retry_response(handler_input: HandlerInput, speech: str, reprompt: str):
    """Keep Alexa's active location intent open so a bare town fills its slot."""
    builder = handler_input.response_builder.speak(ssml(speech)).reprompt(ssml(reprompt))
    slot_name = {
        "TownCaptureIntent": "townName",
        "SetLocationIntent": "location",
    }.get(get_intent_name(handler_input))
    if slot_name:
        builder = builder.add_directive({
            "type": "Dialog.ElicitSlot",
            "slotToElicit": slot_name,
        })
    return builder.set_should_end_session(False).response


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
    activate_dialog(
        handler_input,
        "onboarding",
        context={"stage": "ask_permission"},
    )
    return handler_input.response_builder \
        .speak(ssml(ONBOARDING_ASK_PERMISSION)) \
        .set_should_end_session(False) \
        .response


def handle_permission_yes(handler_input: HandlerInput, store: Dict[str, Any]):
    """Send the Alexa-owned consent card for the location data we consume."""
    permissions = [PERMISSIONS["DEVICE_ADDRESS"]]
    update_store(handler_input, {"onboardingStage": "ask_permission"})
    activate_dialog(
        handler_input,
        "onboarding",
        context={"stage": "ask_permission"},
    )
    logger.info(
        "Hear: permission card requested scopes=%s requestId=%s cardPresent=true",
        permissions,
        _request_id(handler_input),
    )
    return handler_input.response_builder \
        .speak(ssml(ONBOARDING_CONSENT_CARD_SENT)) \
        .with_ask_for_permissions_consent_card(permissions) \
        .set_should_end_session(True) \
        .response


def _request_id(handler_input: HandlerInput) -> str:
    try:
        request = handler_input.request_envelope.request
        return str(request.requestId or "")
    except Exception:
        try:
            return str(handler_input.request_envelope["request"].get("requestId") or "")
        except Exception:
            return ""


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
    activate_dialog(
        handler_input,
        "onboarding",
        context={"stage": ONBOARDING_ASK_TOWN},
    )
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
    activate_dialog(
        handler_input,
        "onboarding",
        context={"stage": ONBOARDING_ASK_TOWN},
    )
    return handler_input.response_builder \
        .speak(ssml(WELCOME_FIRST_ASK_TOWN(name))) \
        .reprompt(ssml(REPROMPT_ASK_TOWN)) \
        .set_should_end_session(False) \
        .response


def resume_town_capture(handler_input: HandlerInput, store: Dict[str, Any]):
    """Retry city capture, then give actionable setup guidance without auto-skipping."""
    attempts = int(store.get("onboardingTownAttempts") or 0) + 1
    update_store(handler_input, {"onboardingTownAttempts": attempts})
    speech = CITY_SETUP_GUIDANCE if attempts >= MAX_TOWN_ATTEMPTS else TOWN_NOT_UNDERSTOOD
    return _town_retry_response(
        handler_input, speech, REPROMPT_ASK_TOWN,
    )


def handle_town_resolver_unavailable(handler_input: HandlerInput, store: Dict[str, Any]):
    """Keep one retry in-session, then finish onboarding without location."""
    failures = int(store.get("onboardingTownResolverFailures") or 0) + 1
    if failures < MAX_TOWN_RESOLVER_FAILURES:
        update_store(handler_input, {
            "onboardingStage": ONBOARDING_ASK_TOWN,
            "onboardingTownResolverFailures": failures,
        })
        activate_dialog(
            handler_input,
            "onboarding",
            context={"stage": ONBOARDING_ASK_TOWN},
        )
        return _town_retry_response(
            handler_input, TOWN_LOOKUP_UNAVAILABLE_RETRY, REPROMPT_ASK_TOWN,
        )

    update_store(handler_input, {
        "onboardingStage": None,
        "onboardingTownAttempts": 0,
        "onboardingTownResolverFailures": 0,
        "onboardingComplete": True,
        "awaitingLocationConfirm": False,
        "pendingLocationConfirm": None,
    })
    clear_active_dialog(handler_input, "onboarding")
    return handler_input.response_builder \
        .speak(ssml(TOWN_LOOKUP_UNAVAILABLE_CONTINUE)) \
        .reprompt(ssml(REPROMPT_NO_CITY)) \
        .set_should_end_session(False) \
        .response


async def stage_town_confirmation(handler_input: HandlerInput, store: Dict[str, Any], phrase: str, *, deps: Dependencies | None = None):
    d = deps or Dependencies()
    logger.info(
        "Hear: resolving town intent=%s phrase=%r",
        get_intent_name(handler_input),
        phrase,
    )
    try:
        response = await d.resolver.resolve_utterance(
            phrase,
            alexa_user_id=get_user_id(handler_input),
            prefer_location=True,
        )
        resolution = response.get("resolution") or {}
    except ResolverUnavailable as exc:
        logger.warning("Hear: town resolver unavailable reason=%s", exc)
        return handle_town_resolver_unavailable(handler_input, store)
    update_store(handler_input, {"onboardingTownResolverFailures": 0})
    match = resolution.get("match")
    candidates = resolution.get("candidates") or []
    logger.info(
        "Hear: onboarding town resolution matched=%s city=%s candidates=%s",
        bool(match),
        (match or {}).get("city"),
        len(candidates),
    )
    if not match:
        if candidates:
            names = [candidate["city"] for candidate in candidates[:2]]
            spoken = " or ".join(names)
            update_store(handler_input, {
                "onboardingTownAttempts": store.get("onboardingTownAttempts", 0) + 1,
            })
            return _town_retry_response(
                handler_input,
                f"Did you mean {spoken}? Please say the full city name.",
                REPROMPT_ASK_TOWN,
            )
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
        "_requiresReliableSave": True,
    })
    _update_onboarding_session(
        handler_input,
        onboardingStage=ONBOARDING_AWAIT_CONFIRM,
        awaitingLocationConfirm=True,
        pendingLocationConfirm=match,
    )
    activate_dialog(
        handler_input,
        "onboarding",
        context={"stage": ONBOARDING_AWAIT_CONFIRM},
    )
    return handler_input.response_builder \
        .speak(ssml(ONBOARDING_TOWN_CONFIRM(match["city"]))) \
        .reprompt(ssml(TOWN_CONFIRM_REPROMPT)) \
        .set_should_end_session(False) \
        .response


async def finalize_town_captured(
    handler_input: HandlerInput,
    store: Dict[str, Any],
    phrase: str,
    *,
    deps: Dependencies | None = None,
):
    d = deps or Dependencies()
    try:
        response = await d.resolver.resolve_utterance(
            phrase,
            alexa_user_id=get_user_id(handler_input),
            prefer_location=True,
        )
        resolution = response.get("resolution") or {}
    except ResolverUnavailable as exc:
        logger.warning("Hear: town resolver unavailable reason=%s", exc)
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
        "_requiresReliableSave": True,
    })
    _update_onboarding_session(
        handler_input,
        onboardingStage=None,
        awaitingLocationConfirm=False,
    )
    clear_active_dialog(handler_input, "onboarding")
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
        "awaitingLocationConfirm": False,
        "pendingLocationConfirm": None,
        "_requiresReliableSave": True,
    })
    _update_onboarding_session(
        handler_input,
        onboardingStage=None,
        awaitingLocationConfirm=False,
    )
    clear_active_dialog(handler_input, "onboarding")

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
    activate_dialog(
        handler_input,
        "onboarding",
        context={"stage": ONBOARDING_ASK_TOWN},
    )
    return handler_input.response_builder \
        .speak(ssml(LOCATION_NOT_FOUND)) \
        .reprompt(ssml(REPROMPT_ASK_TOWN)) \
        .set_should_end_session(False) \
        .response


async def auto_detect_location_or_manual(handler_input: HandlerInput, store: Dict[str, Any], *, deps: Dependencies | None = None):
    d = deps or Dependencies()
    match = await d.locality.detect_device_location(handler_input)
    if not match or match.get("_status") == "permission_denied":
        return ask_for_permission(handler_input, store)
    if match.get("_status") != "resolved":
        return handle_location_not_found(handler_input, store)
    if not match.get("city"):
        update_store(handler_input, {
            "latitude": match.get("latitude"),
            "longitude": match.get("longitude"),
            "_requiresReliableSave": True,
        })
        return handle_location_not_found(handler_input, store)
    if match.get("latitude") is None or match.get("longitude") is None:
        try:
            response = await d.resolver.resolve_utterance(
                match["city"],
                alexa_user_id=get_user_id(handler_input),
                prefer_location=True,
            )
            resolved = (response.get("resolution") or {}).get("match")
        except ResolverUnavailable as exc:
            logger.warning(
                "Hear: device-address coordinate resolution unavailable reason=%s",
                exc,
            )
            resolved = None
        if not resolved:
            logger.info(
                "Hear: device-address city could not be resolved to coordinates city=%s",
                match.get("city"),
            )
            return handle_location_not_found(handler_input, store)
        # Keep address-specific metadata while preferring the resolver's
        # canonical locality and coordinates.
        match = {
            **match,
            **resolved,
            "postalCode": match.get("postalCode"),
            "source": "device",
            "_status": "resolved",
        }
        logger.info(
            "Hear: device-address city resolved coordinates=true city=%s",
            match.get("city"),
        )
    update_store(handler_input, {
        "pendingLocationConfirm": match,
        "awaitingLocationConfirm": True,
        "onboardingStage": ONBOARDING_AWAIT_CONFIRM,
        "onboardingTownAttempts": 0,
        "_requiresReliableSave": True,
    })
    _update_onboarding_session(
        handler_input,
        onboardingStage=ONBOARDING_AWAIT_CONFIRM,
        awaitingLocationConfirm=True,
    )
    activate_dialog(
        handler_input,
        "onboarding",
        context={"stage": ONBOARDING_AWAIT_CONFIRM},
    )
    return handler_input.response_builder \
        .speak(ssml(ONBOARDING_DEVICE_TOWN_CONFIRM(match["city"]))) \
        .reprompt(ssml(TOWN_CONFIRM_REPROMPT)) \
        .set_should_end_session(False) \
        .response


