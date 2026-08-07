from __future__ import annotations

import logging
import time

from src.services.api import sync_listener
from src.services.storage.persistence import get_store, update_store
from src.utils.skill_request import get_user_id

logger = logging.getLogger(__name__)


def _request_context(handler_input) -> tuple[str | None, str | None, str | None]:
    request = getattr(handler_input.request_envelope, "request", None)
    locale = getattr(request, "locale", None)
    try:
        system = handler_input.request_envelope.context.System
        device_id = system.device.deviceId
        api_endpoint = system.apiEndpoint
    except (AttributeError, KeyError):
        device_id = None
        api_endpoint = None
    return device_id, api_endpoint, locale


def build_listener_sync_profile(handler_input, store: dict) -> dict | None:
    """Build the documented listener-sync payload from canonical state."""
    alexa_user_id = get_user_id(handler_input)
    if not alexa_user_id:
        return None
    device_id, api_endpoint, locale = _request_context(handler_input)
    recent = [
        item.get("contentId")
        for item in (store.get("recentTrackListens") or store.get("history") or [])
        if isinstance(item, dict) and item.get("contentId")
    ]
    return {
        "alexaUserId": alexa_user_id,
        "deviceId": device_id,
        "apiEndpoint": api_endpoint,
        "locale": locale,
        "userName": (
            store.get("userName")
            or store.get("fullName")
            or store.get("givenName")
        ),
        "userEmail": store.get("userEmail"),
        "address": store.get("address"),
        "city": store.get("userCity") or store.get("city"),
        "state": store.get("state"),
        "country": store.get("country"),
        "countryCode": store.get("deviceCountryCode") or store.get("countryCode"),
        "postalCode": store.get("devicePostalCode") or store.get("postalCode"),
        "latitude": store.get("latitude"),
        "longitude": store.get("longitude"),
        "clientVersion": "hear-alexa-python",
        "locality": store.get("locality"),
        "listeningPattern": store.get("listeningPattern"),
        "followedCreatorIds": list(store.get("followedCreators") or []),
        "playbackSpeed": store.get("playbackSpeed"),
        "playCount": int(store.get("playCount") or 0),
        "lastPlayedAt": store.get("lastPlayedAt"),
        "recentPlayedIds": list(dict.fromkeys(recent))[-20:],
        "recentPlays": list(store.get("recentTrackListens") or [])[-20:],
    }


async def sync_listener_for_launch(handler_input) -> bool:
    """Upsert the Alexa listener on every foreground launch."""
    store = get_store(handler_input)
    profile = build_listener_sync_profile(handler_input, store)
    if not profile:
        return False
    logger.info(
        "Hear: listener sync request fields=%s hasLocation=%s playCount=%s",
        sorted(key for key, value in profile.items() if value not in (None, [], {})),
        bool(profile.get("locality") or profile.get("city")),
        profile.get("playCount", 0),
    )
    result = await sync_listener(profile, timeout_ms=2500)
    if not result:
        logger.warning("Hear: listener sync failed")
        return False
    listener_id = result.get("listenerId") or result.get("id")
    update_store(handler_input, {
        "listenerId": listener_id or store.get("listenerId"),
        "listenerSyncedAt": int(time.time() * 1000),
    })
    logger.info(
        "Hear: listener sync success hasListenerId=%s",
        bool(listener_id or store.get("listenerId")),
    )
    return True
