from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.services.playback.session import read_playback_session, write_playback_session
from src.services.storage.persistence import get_store, update_store
from src.utils.skill_request import get_request_type


class PlaybackProgressReportHandler(AbstractRequestHandler):
    def can_handle(self, handler_input) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackProgressReport"

    async def handle(self, handler_input):
        request = handler_input.request_envelope.request
        token = request.token
        offset_ms = max(0, int(request.offset_in_milliseconds or 0))
        state = read_playback_session(get_store(handler_input))
        if state and state.get("contentId") == token and state.get("status") in {
            "starting", "playing", "paused",
        }:
            listened_ms = max(int(state.get("listenedMs") or 0), offset_ms)
            write_playback_session(handler_input, {
                "offsetMs": offset_ms,
                "listenedMs": listened_ms,
                "status": "playing",
            })
            update_store(handler_input, {
                "lastOffsetMs": offset_ms,
                "lastToken": token,
            })
        return handler_input.response_builder.response
