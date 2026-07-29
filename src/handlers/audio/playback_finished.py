from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.services.feedback.candidates import (
    activate_best_feedback_candidate,
    record_feedback_candidate,
)
from src.services.playback.events import emit_listening_event
from src.services.playback.session import read_playback_session, write_playback_session
from src.services.queue.state import read_playback_queue
from src.services.storage.persistence import get_store
from src.utils.skill_request import get_request_type


class PlaybackFinishedHandler(AbstractRequestHandler):
    def can_handle(self, handler_input) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackFinished"

    async def handle(self, handler_input):
        request = handler_input.request_envelope.request
        token = request.token
        offset_ms = max(0, int(request.offset_in_milliseconds or 0))
        state = read_playback_session(get_store(handler_input))
        if state and state.get("contentId") == token:
            duration_ms = int(state.get("durationMs") or 0)
            listened_ms = max(
                int(state.get("listenedMs") or 0),
                offset_ms,
                duration_ms,
            )
            state = write_playback_session(handler_input, {
                "status": "completed",
                "offsetMs": max(offset_ms, duration_ms),
                "listenedMs": listened_ms,
            })
            record_feedback_candidate(handler_input, state, completed=True)
            await emit_listening_event(handler_input, "finished", state)
            queue = read_playback_queue(get_store(handler_input))
            has_prepared_next = bool(get_store(handler_input).get("preparedNextContent"))
            if not queue or (
                int(queue.get("currentIndex") or 0) >= len(queue["orderedContentIds"]) - 1
                and not has_prepared_next
            ):
                activate_best_feedback_candidate(handler_input)
        return handler_input.response_builder.response
