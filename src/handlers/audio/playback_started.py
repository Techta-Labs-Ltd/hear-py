from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.services.notifications import consume_notification_for_playback
from src.services.playback.events import emit_listening_event
from src.services.playback.session import (
    create_playback_session,
    read_playback_session,
    write_playback_session,
)
from src.services.queue.state import read_playback_queue, set_queue_index_for_content
from src.services.storage.persistence import get_store, update_store
from src.utils.skill_request import (
    get_audio_player_offset_ms,
    get_audio_player_token,
    get_request_type,
    get_user_id,
)


class PlaybackStartedHandler(AbstractRequestHandler):
    def can_handle(self, handler_input) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackStarted"

    async def handle(self, handler_input):
        token = get_audio_player_token(handler_input)
        offset_ms = get_audio_player_offset_ms(handler_input)
        store = get_store(handler_input)
        state = read_playback_session(store)
        prepared = store.get("preparedNextContent")
        if (
            isinstance(prepared, dict)
            and prepared.get("contentId") == token
            and (not state or state.get("contentId") != token)
        ):
            queue_index = set_queue_index_for_content(handler_input, token) or 0
            queue = read_playback_queue(get_store(handler_input))
            state = create_playback_session(
                handler_input,
                prepared,
                queue_id=queue.get("queueId") if queue else None,
                queue_index=queue_index,
                offset_ms=offset_ms,
            )
            update_store(handler_input, {"preparedNextContent": None})
        if state and state.get("contentId") == token:
            state = write_playback_session(handler_input, {
                "status": "playing",
                "offsetMs": offset_ms,
                "listenedMs": max(int(state.get("listenedMs") or 0), offset_ms),
            })
            update_store(handler_input, {
                "lastToken": token,
                "lastOffsetMs": offset_ms,
            })
            await consume_notification_for_playback(
                get_user_id(handler_input),
                token,
                state.get("publicationId"),
            )
            await emit_listening_event(handler_input, "started", state)
        return handler_input.response_builder.response
