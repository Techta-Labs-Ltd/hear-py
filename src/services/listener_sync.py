from __future__ import annotations

import logging

from config import settings
from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.clients.hear import HearApiClient
from src.models.listener import Listener
from src.models.user import User


class ListenerSyncSupport:
    logger = logging.getLogger(__name__)
    _CLIENT_VERSION = settings.HEAR_CLIENT_VERSION

    @staticmethod
    def build_listener_sync_profile(handler_input, store: dict) -> dict | None:
        alexa_user_id = AlexaRequest.get_user_id(handler_input)
        if not alexa_user_id:
            return None
        system = RequestContext.get_system_context(handler_input)
        request = getattr(handler_input.request_envelope, "request", None)
        device = getattr(system, "device", None)
        registered = bool(
            store.get("userEmail")
            and (store.get("userName") or store.get("fullName") or store.get("givenName"))
        )
        identity = Listener.identity(handler_input)
        profile = {
            "alexaUserId": alexa_user_id,
            "listenerId": store.get("listenerId")
            or (identity.listener_id if identity else None),
            "skillId": identity.skill_id if identity else None,
            "environment": settings.STAGE,
            "principalType": identity.principal_type.value if identity else None,
            "deviceId": getattr(device, "deviceId", None),
            "apiEndpoint": getattr(system, "apiEndpoint", None),
            "locale": getattr(request, "locale", None),
            "listenerType": "registered" if registered else "guest",
            "clientVersion": ListenerSyncSupport._CLIENT_VERSION,
            "playbackSpeed": store.get("playbackSpeed"),
        }
        if registered:
            profile.update(
                {
                    "userName": store.get("userName")
                    or store.get("fullName")
                    or store.get("givenName"),
                    "userEmail": store.get("userEmail"),
                    "address": store.get("userAddress") or store.get("address"),
                    "city": store.get("userCity") or store.get("city"),
                    "state": store.get("userState") or store.get("state"),
                    "country": store.get("userCountry") or store.get("country"),
                    "countryCode": store.get("deviceCountryCode")
                    or store.get("countryCode"),
                    "postalCode": store.get("devicePostalCode") or store.get("postalCode"),
                    "latitude": store.get("latitude"),
                    "longitude": store.get("longitude"),
                    "locality": store.get("locality"),
                }
            )
        return profile

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
            "Hear: listener sync request fields=%s hasLocation=%s hasProfile=%s",
            sorted((key for key, value in profile.items() if value not in (None, [], {}))),
            bool(profile.get("locality") or profile.get("city")),
            bool(profile.get("userEmail") or profile.get("userName")),
        )
        result = await self._hear_api.sync_listener(profile, timeout_ms=2500)
        if not result:
            ListenerSyncSupport.logger.warning("Hear: listener sync failed")
            return False
        listener_id = result.get("listenerId")
        User.update(handler_input, {"listenerId": listener_id or store.get("listenerId")})
        ListenerSyncSupport.logger.info(
            "Hear: listener sync success hasListenerId=%s",
            bool(listener_id or store.get("listenerId")),
        )
        return True
