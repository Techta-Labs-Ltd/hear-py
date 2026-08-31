from __future__ import annotations

import logging
import time

from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.clients.hear import HearApiClient
from src.models.user import User
from src.utils.playback_history import PlaybackHistoryUtils


class ListenerSyncSupport:
    logger = logging.getLogger(__name__)
    _CLIENT_VERSION = "hear-alexa-python"

    @staticmethod
    def build_listener_sync_profile(handler_input, store: dict) -> dict | None:
        alexa_user_id = AlexaRequest.get_user_id(handler_input)
        if not alexa_user_id:
            return None
        system = RequestContext.get_system_context(handler_input)
        request = getattr(handler_input.request_envelope, "request", None)
        device = getattr(system, "device", None)
        recent_plays = [
            normalized
            for item in store.get("playHistory") or []
            if (normalized := PlaybackHistoryUtils.normalize(item))
        ][:20]
        recent = [
            item.get("subjectId") or item.get("publicationId") or item.get("contentId")
            for item in recent_plays
            if item.get("subjectId") or item.get("publicationId") or item.get("contentId")
        ]
        registered = bool(
            store.get("userEmail")
            and (store.get("userName") or store.get("fullName") or store.get("givenName"))
        )
        profile = {
            "alexaUserId": alexa_user_id,
            "deviceId": getattr(device, "deviceId", None),
            "apiEndpoint": getattr(system, "apiEndpoint", None),
            "locale": getattr(request, "locale", None),
            "listenerType": "registered" if registered else "guest",
            "clientVersion": ListenerSyncSupport._CLIENT_VERSION,
            "listeningPattern": store.get("listeningPattern"),
            "followedCreatorIds": ListenerSyncSupport._followed_ids(store, "creator"),
            "followedOrganizationIds": ListenerSyncSupport._followed_ids(store, "organization"),
            "playbackSpeed": store.get("playbackSpeed"),
            "playCount": int(store.get("playCount") or 0),
            "lastPlayedAt": store.get("lastPlayedAt"),
            "recentPlayedIds": list(dict.fromkeys(recent))[-20:],
            "recentPlays": recent_plays,
        }
        if registered:
            profile.update(
                {
                    "userName": store.get("userName")
                    or store.get("fullName")
                    or store.get("givenName"),
                    "userEmail": store.get("userEmail"),
                    "address": store.get("address"),
                    "city": store.get("userCity") or store.get("city"),
                    "state": store.get("state"),
                    "country": store.get("country"),
                    "countryCode": store.get("deviceCountryCode")
                    or store.get("countryCode"),
                    "postalCode": store.get("devicePostalCode") or store.get("postalCode"),
                    "latitude": store.get("latitude"),
                    "longitude": store.get("longitude"),
                    "locality": store.get("locality"),
                }
            )
        return profile

    @staticmethod
    def _followed_ids(store: dict, source_type: str) -> list[str]:
        return [
            str(item["id"])
            for item in store.get("followedCreators") or []
            if isinstance(item, dict)
            and item.get("id")
            and (item.get("type", "creator") == source_type)
        ]


class ListenerSyncService:
    __slots__ = ("_hear_api", "_enabled")

    def __init__(self, hear_api: HearApiClient, *, enabled: bool = True) -> None:
        self._hear_api = hear_api
        self._enabled = enabled

    async def sync_for_launch(self, handler_input) -> bool:
        if not self._enabled:
            return False
        store = User.snapshot(handler_input)
        profile = ListenerSyncSupport.build_listener_sync_profile(handler_input, store)
        if not profile:
            return False
        ListenerSyncSupport.logger.info(
            "Hear: listener sync request fields=%s hasLocation=%s playCount=%s",
            sorted((key for key, value in profile.items() if value not in (None, [], {}))),
            bool(profile.get("locality") or profile.get("city")),
            profile.get("playCount", 0),
        )
        result = await self._hear_api.sync_listener(profile, timeout_ms=2500)
        if not result:
            ListenerSyncSupport.logger.warning("Hear: listener sync failed")
            return False
        listener_id = result.get("listenerId") or result.get("id")
        User.update(
            handler_input,
            {
                "listenerId": listener_id or store.get("listenerId"),
                "listenerSyncedAt": int(time.time() * 1000),
            },
        )
        ListenerSyncSupport.logger.info(
            "Hear: listener sync success hasListenerId=%s",
            bool(listener_id or store.get("listenerId")),
        )
        return True
