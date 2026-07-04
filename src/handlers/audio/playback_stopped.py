from __future__ import annotations

import logging
import time

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.services.persistence import get_store, update_store
from src.services.alexa_api_client import send_playback_events, get_alexa_user_id
from src.utils.skill_request import get_request_type
from src.utils.playback_event_builder import (
    build_playback_event, resolve_playback_event_media, alexa_timestamp_from_request,
)
from src.utils.playback_timing import resolve_playback_event_timing, playback_state_duration_patch
from src.utils.playback_session import resolve_playback_state, save_playback_state, write_playback_session
from src.utils.listen_tracker import (
    is_feedback_token, content_id_from_feedback_token, close_listen_segment,
)
from src.utils.listen_log import summarize_listen_ms
from src.utils.playback_user_events import consume_suppressed_playback_event

logger = logging.getLogger(__name__)


class PlaybackStoppedHandler(AbstractRequestHandler):
    """Handles AudioPlayer.PlaybackStopped — records offset and sends analytics."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackStopped"

    async def handle(self, handler_input: HandlerInput):
        req = handler_input.request_envelope.request
        token = req.token
        offset_ms = req.offset_in_milliseconds or 0

        update_store(handler_input, {
            "lastToken": content_id_from_feedback_token(token) if is_feedback_token(token) else token,
            "lastOffsetMs": offset_ms,
        })

        if not is_feedback_token(token):
            alexa_user_id = get_alexa_user_id(handler_input)
            now = int(time.time() * 1000)
            resolved = await resolve_playback_state(alexa_user_id, handler_input)
            state = resolved.get("state")

            if state:
                await save_playback_state(alexa_user_id, handler_input, {
                    **state,
                    "lastKnownOffsetMs": offset_ms,
                    "lastKnownOffsetUpdatedAt": now,
                    **playback_state_duration_patch(state, get_store(handler_input), offset_ms),
                })
            else:
                write_playback_session(handler_input, {
                    "lastKnownOffsetMs": offset_ms,
                    "lastKnownOffsetUpdatedAt": now,
                })

            close_listen_segment(handler_input, {"offsetMs": offset_ms})

            resolved2 = await resolve_playback_state(alexa_user_id, handler_input)
            resolved_state = resolved2.get("state")
            skip_stopped = consume_suppressed_playback_event(handler_input, "stopped")
            if resolved_state and resolved_state.get("trackId") \
                    and resolved_state.get("sessionId") and not skip_stopped:
                store_now = get_store(handler_input)
                result = resolve_playback_event_timing({
                    "state": resolved_state,
                    "store": store_now,
                    "positionMs": offset_ms,
                })
                position_ms = result.get("positionMs")
                track_duration_ms = result.get("trackDurationMs")
                media = resolve_playback_event_media(store_now, resolved_state)

                try:
                    await send_playback_events({
                        "alexaUserId": alexa_user_id,
                        "handlerInput": handler_input,
                        "events": [
                            build_playback_event({
                                "sessionId": resolved_state["sessionId"],
                                "trackId": resolved_state["trackId"],
                                "eventType": "AUDIO_PLAYER_PLAYBACK_STOPPED",
                                "positionMs": position_ms,
                                "trackDurationMs": track_duration_ms,
                                "eventLabel": "STOPPED",
                                "timestamp": now,
                                "alexaTimestamp": alexa_timestamp_from_request(req),
                                **media,
                            }),
                        ],
                        "refreshTrackIds": [resolved_state["trackId"]],
                    })
                except Exception:
                    pass

                logger.info(
                    "Hear: playback event time spent trackId=%s eventType=AUDIO_PLAYER_PLAYBACK_STOPPED %s",
                    resolved_state["trackId"],
                    summarize_listen_ms(
                        position_ms,
                        track_duration_ms / 1000 if track_duration_ms
                        else get_store(handler_input).get("currentDurationSecs"),
                    ),
                )

        return handler_input.response_builder.response
