from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ask_sdk_core.handler_input import HandlerInput

from config import settings
from config.permission_scopes import DEVICE_ADDRESS, GEOLOCATION_READ

from src.services.persistence import get_store, update_store
from src.services.locality import get_device_address, get_geolocation
from src.webhooks.dispatch import dispatch
from src.services.api import resolve_locality
from src.utils.speech import (
    ssml, ONBOARDING_ASK_PERMISSION, ONBOARDING_CONSENT_CARD_SENT,
    ONBOARDING_LOCATION_DENIED, ONBOARDING_FETCHING_LOCATION, ONBOARDING_DISCOVERY,
    ONBOARDING_RESOLVE_FAILED, WELCOME_FIRST_ASK_TOWN, REPROMPT_ASK_TOWN,
    TOWN_NOT_UNDERSTOOD, TOWN_GOT_IT, REPROMPT_CITY, TOWN_SKIPPED, REPROMPT_NO_CITY,
    WELCOME_RETURN_NAMED, WELCOME_RETURN_CITY, WELCOME_RETURN_GENERIC,
    ONBOARDING_NO_LOCAL_CONTENT, ONBOARDING_DISCOVERY_NATIONAL,
)

ONBOARDING_ASK_TOWN = "ask_town"
MAX_TOWN_ATTEMPTS = 3
PERMISSIONS = {"DEVICE_ADDRESS": DEVICE_ADDRESS, "GEOLOCATION": GEOLOCATION_READ}
logger = logging.getLogger(__name__)


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
        .set_should_end_session(False) \
        .response


def handle_permission_no(handler_input: HandlerInput, store: Dict[str, Any]):
    """Handle permission denial — fall back to manual town entry."""
    update_store(handler_input, {
        "onboardingStage": ONBOARDING_ASK_TOWN,
        "onboardingRetries": 0,
        "_requiresReliableSave": True,
    })
    return handler_input.response_builder \
        .speak(ssml(ONBOARDING_LOCATION_DENIED)) \
        .set_should_end_session(False) \
        .response


async def resume_after_location_grant(handler_input: HandlerInput, store: Dict[str, Any]):
    try:
        address = await get_device_address(handler_input)
        geo = get_geolocation(handler_input)

        if address and not address.get("denied"):
            payload = {
                "postalCode": address.get("postalCode"),
                "countryCode": address.get("countryCode"),
                "latitude": geo.get("latitude") if geo else None,
                "longitude": geo.get("longitude") if geo else None,
            }

            resolved = await resolve_locality(payload)
            if resolved and resolved.get("city"):
                update_store(handler_input, {
                    "userCity": resolved["city"],
                    "locality": resolved.get("locality") or resolved["city"],
                    "userState": resolved.get("state"),
                    "userCountry": resolved.get("country"),
                    "devicePostalCode": address.get("postalCode"),
                    "deviceCountryCode": address.get("countryCode"),
                    "latitude": resolved.get("latitude"),
                    "longitude": resolved.get("longitude"),
                    "onboardingComplete": True,
                    "onboardingStage": "done",
                    "locationSource": "device",
                    "localityResolvedAt": int(time.time() * 1000),
                })
                return handler_input.response_builder \
                    .speak(ssml(ONBOARDING_DISCOVERY(resolved["city"], 0))) \
                    .set_should_end_session(False) \
                    .response

        if address and address.get("denied"):
            update_store(handler_input, {
                "onboardingStage": ONBOARDING_ASK_TOWN,
                "onboardingRetries": 0,
            })
            return handler_input.response_builder \
                .speak(ssml(ONBOARDING_LOCATION_DENIED)) \
                .set_should_end_session(False) \
                .response
    except Exception as err:
        logger.warning("Hear: resume_after_location_grant failed %s", err)

    update_store(handler_input, {
        "onboardingStage": ONBOARDING_ASK_TOWN,
        "onboardingRetries": 0,
    })
    return handler_input.response_builder \
        .speak(ssml(ONBOARDING_RESOLVE_FAILED)) \
        .set_should_end_session(False) \
        .response


async def confirm_manual_town(handler_input: HandlerInput, store: Dict[str, Any], city: str):
    try:
        resolved = await resolve_locality({"q": city})
        if resolved and resolved.get("city"):
            update_store(handler_input, {
                "userCity": resolved["city"],
                "locality": resolved.get("locality") or resolved["city"],
                "userState": resolved.get("state"),
                "userCountry": resolved.get("country"),
                "latitude": resolved.get("latitude"),
                "longitude": resolved.get("longitude"),
                "devicePostalCode": resolved.get("postalCode"),
                "onboardingComplete": True,
                "onboardingStage": "done",
                "locationSource": "manual",
                "localityResolvedAt": int(time.time() * 1000),
            })
            return handler_input.response_builder \
                .speak(ssml(ONBOARDING_DISCOVERY(resolved["city"], 0))) \
                .set_should_end_session(False) \
                .response
    except Exception:
        pass

    update_store(handler_input, {
        "userCity": city,
        "locality": city,
        "localityResolvedAt": int(time.time() * 1000),
        "onboardingComplete": True,
        "onboardingStage": "done",
        "locationSource": "manual",
    })
    return handler_input.response_builder \
        .speak(ssml(ONBOARDING_DISCOVERY(city, 0))) \
        .set_should_end_session(False) \
        .response


def handle_returning_user(
    handler_input: HandlerInput,
    store: Dict[str, Any],
    resolved_user_name: Optional[str],
    resolved_locality: Optional[str],
):
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


async def finalize_town_captured(handler_input: HandlerInput, store: Dict[str, Any], city: str):
    """Persist the captured town and acknowledge it to the user."""
    try:
        user_id = handler_input.request_envelope.context.System.user.userId or None
    except Exception:
        user_id = None

    if city and user_id:
        update_store(handler_input, {
            "userCity": city,
            "locality": city,
            "localityResolvedAt": int(time.time() * 1000),
        })
        try:
            dispatch("user.location_updated", {
                "userId": user_id,
                "listenerId": None,
                "city": city,
                "timestamp": int(time.time() * 1000),
            })
        except Exception:
            pass

    updated_store = get_store(handler_input)
    resolved_city = updated_store.get("userCity") or updated_store.get("locality") or city

    update_store(handler_input, {
        "onboardingStage": None,
        "onboardingTownAttempts": 0,
    })

    logger.info("Hear: onboarding town captured city=%s", resolved_city)

    return handler_input.response_builder \
        .speak(ssml(TOWN_GOT_IT(resolved_city))) \
        .reprompt(ssml(REPROMPT_CITY(resolved_city))) \
        .set_should_end_session(False) \
        .response


def finalize_town_skipped(handler_input: HandlerInput, store: Dict[str, Any]):
    """Skip town capture and proceed without location."""
    update_store(handler_input, {
        "onboardingStage": None,
        "onboardingTownAttempts": 0,
    })

    logger.info("Hear: onboarding town skipped")

    return handler_input.response_builder \
        .speak(ssml(TOWN_SKIPPED)) \
        .reprompt(ssml(REPROMPT_NO_CITY)) \
        .set_should_end_session(False) \
        .response
