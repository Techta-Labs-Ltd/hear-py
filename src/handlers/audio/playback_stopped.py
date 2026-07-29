from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.services.feedback.candidates import record_feedback_candidate
from src.services.playback.events import emit_listening_event
from src.services.playback.session import read_playback_session, write_playback_session
from src.services.storage.persistence import get_store, update_store
from src.utils.skill_request import get_request_type


class PlaybackStoppedHandler(AbstractRequestHandler):
    def can_handle(self, handler_input) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackStopped"

    async def handle(self, handler_input):
        request = handler_input.request_envelope.request
        token = request.token
        offset_ms = max(0, int(request.offset_in_milliseconds or 0))
        state = read_playback_session(get_store(handler_input))
        if state and state.get("contentId") == token:
            state = write_playback_session(handler_input, {
                "status": "paused",
                "offsetMs": offset_ms,
                "listenedMs": max(int(state.get("listenedMs") or 0), offset_ms),
            })
            update_store(handler_input, {"lastOffsetMs": offset_ms, "lastToken": token})
            record_feedback_candidate(handler_input, state, completed=False)
            await emit_listening_event(handler_input, "stopped", state)
        return handler_input.response_builder.response
