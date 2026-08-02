from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.services.notifications import reset_notification_for_playback
from src.services.playback.events import emit_listening_event
from src.services.playback.session import read_playback_session, write_playback_session
from src.services.storage.persistence import get_store, update_store
from src.utils.skill_request import get_request_type, get_user_id

logger = logging.getLogger(__name__)


class PlaybackFailedHandler(AbstractRequestHandler):
    def can_handle(self, handler_input) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackFailed"

    async def handle(self, handler_input):
        request = handler_input.request_envelope.request
        token = request.token
        state = read_playback_session(get_store(handler_input))
        if state and state.get("contentId") == token:
            previous_status = state.get("status")
            state = write_playback_session(handler_input, {"status": "failed"})
            if previous_status == "starting":
                await reset_notification_for_playback(
                    get_user_id(handler_input),
                    token,
                    state.get("publicationId"),
                )
            await emit_listening_event(handler_input, "failed", state)
            update_store(handler_input, {"preparedNextContent": None})
        logger.warning("Hear audio playback failed contentId=%s", token)
        return handler_input.response_builder.response
