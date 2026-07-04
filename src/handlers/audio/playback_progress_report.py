"""
PlaybackProgressReportHandler - Handles PlaybackProgressReport events from Alexa.
Updates periodic offset and playback state duration estimates.
"""
from __future__ import annotations

import logging
import time

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.services.persistence import get_store, update_store
from src.services.alexa_api_client import get_alexa_user_id
from src.utils.skill_request import get_request_type
from src.utils.listen_tracker import is_feedback_token
from src.utils.playback_session import resolve_playback_state, save_playback_state
from src.utils.playback_timing import playback_state_duration_patch

logger = logging.getLogger(__name__)


def _is_wrapper_or_outro_token(token: str) -> bool:
    """Check if a token belongs to a wrapper/outro audio segment."""
    return token and (str(token).startswith("wrapper-") or str(token).startswith("outro-"))


class PlaybackProgressReportHandler(AbstractRequestHandler):
    """Handles AudioPlayer.PlaybackProgressReport — updates offset and duration estimates."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackProgressReport"

    async def handle(self, handler_input: HandlerInput):
        req = handler_input.request_envelope.request
        token = req.token
        offset_ms = req.offset_in_milliseconds or 0

        if is_feedback_token(token) or _is_wrapper_or_outro_token(token):
            return handler_input.response_builder.response

        store = get_store(handler_input)
        offset_patch = {"lastOffsetMs": offset_ms, "lastToken": token}
        if offset_ms > 0:
            offset_patch["playbackDurationEstimateMs"] = max(
                store.get("playbackDurationEstimateMs") or 0, offset_ms,
            )
        update_store(handler_input, offset_patch)

        alexa_user_id = get_alexa_user_id(handler_input)
        resolved = await resolve_playback_state(alexa_user_id, handler_input)
        playback_state = resolved.get("state")
        if playback_state and isinstance(offset_ms, (int, float)) and offset_ms >= 0:
            store_now = get_store(handler_input)
            await save_playback_state(alexa_user_id, handler_input, {
                **playback_state,
                "lastKnownOffsetMs": offset_ms,
                "lastKnownOffsetUpdatedAt": int(time.time() * 1000),
                **playback_state_duration_patch(playback_state, store_now, offset_ms),
            })

        return handler_input.response_builder.response
