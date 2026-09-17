from __future__ import annotations

from src.clients.hear import HearApiClient
from src.models.user import User
from src.services.listener_repository import Listener
from src.utils.listener_payload import ListenerPayload


class ListenerSyncPayload:
    @staticmethod
    def build(handler_input, store: dict) -> dict | None:
        identity = Listener.identity(handler_input)
        if identity is None or not identity.alexa_user_id:
            return None
        profile = {
            "action": "alexa",
            "alexaUserId": identity.alexa_user_id,
            "listenerId": identity.listener_id,
        }
        values = {
            "listenerName": ListenerPayload.text(
                store.get("userName") or store.get("fullName"), ListenerPayload.MAX_TEXT_LENGTH
            ),
            "email": ListenerPayload.email(store.get("userEmail")),
            "city": ListenerPayload.text(store.get("userCity"), ListenerPayload.MAX_TEXT_LENGTH),
            "latitude": store.get("latitude"),
            "longitude": store.get("longitude"),
        }
        return {**profile, **{key: value for key, value in values.items() if value is not None}}

class ListenerSyncService:
    __slots__ = ("_hear_api", "_enabled")

    def __init__(self, hear_api: HearApiClient, *, enabled: bool = True) -> None:
        self._hear_api = hear_api
        self._enabled = enabled

    async def sync_for_launch(self, handler_input) -> bool:
        if not self._enabled:
            return False
        store = User.snapshot(handler_input)
        profile = ListenerSyncPayload.build(handler_input, store)
        if not profile:
            return False
        result = await self._hear_api.sync_listener(profile, timeout_ms=2500)
        if not result:
            return False
        listener_id = str(result.get("listenerId") or "").strip()
        identity = Listener.identity(handler_input)
        if listener_id and identity is not None:
            Listener.set_identity(handler_input, identity.with_listener_id(listener_id))
        return True
