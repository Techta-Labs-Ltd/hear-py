from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor

from src.alexa.following_state import FollowingSessionState
from src.alexa.request import AlexaRequest
from src.services.logging_control import ApplicationLog


class ListenerSessionSyncInterceptor(AbstractRequestInterceptor):
    """Hydrate backend-owned follow state when a session starts with an intent."""

    def __init__(self, listener_sync) -> None:
        self._listener_sync = listener_sync

    async def process(self, handler_input) -> None:
        if AlexaRequest.get_request_type(handler_input) != "IntentRequest":
            return
        session = AlexaRequest.read(handler_input.request_envelope, "session")
        if not bool(AlexaRequest.read(session, "new")):
            return
        if FollowingSessionState.followed_sources(handler_input) is not None:
            return
        try:
            await self._listener_sync.sync_for_launch(handler_input)
        except Exception as exc:
            ApplicationLog.warning(
                "Hear: listener direct-session sync failed error=%s",
                type(exc).__name__,
            )
