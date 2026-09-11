from __future__ import annotations

import logging

from src.alexa.request import AlexaRequest
from src.clients.hear import HearApiClient
from src.models.listener import Listener
from src.models.user import User


class ListenerSyncSupport:
    logger = logging.getLogger(__name__)

    @staticmethod
    def build_listener_sync_profile(handler_input, store: dict) -> dict | None:
        alexa_user_id = AlexaRequest.get_user_id(handler_input)
        if not alexa_user_id:
            return None
        identity = Listener.identity(handler_input)
        raw_listener_name = store.get("userName") or store.get("fullName")
        raw_email = store.get("userEmail")
        listener_name = str(raw_listener_name or "").strip()
        email = str(raw_email or "").strip().lower()
        profile = {
            "action": "alexa",
            "alexaUserId": alexa_user_id,
            "listenerId": store.get("listenerId")
            or (identity.listener_id if identity else None),
        }
        if listener_name and email:
            profile.update(
                {
                    "listenerName": listener_name,
                    "email": email,
                    "city": store.get("userCity") or store.get("city"),
                    "latitude": store.get("latitude"),
                    "longitude": store.get("longitude"),
                }
            )
        return {
            key: value
            for key, value in profile.items()
            if value is not None or key == "listenerId"
        }

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
            bool(profile.get("city")),
            bool(profile.get("email") or profile.get("listenerName")),
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
