"""
PlaybackStartedHandler - Handles AudioPlayer.PlaybackStarted events.
Persists token, offset, and sends playback event analytics.
"""
from __future__ import annotations

import logging
import time

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.services.persistence import get_store, update_store
from src.services.alexa_api_client import send_playback_events, get_alexa_user_id
from src.services.flush_previous_track import flush_previous_track
from src.utils.skill_request import get_request_type
from src.utils.playback_event_builder import (
    build_playback_event, resolve_playback_event_media, alexa_timestamp_from_request,
)
from src.utils.playback_timing import duration_ms_from_store
from src.utils.playback_session import resolve_playback_state, save_playback_state
from src.utils.listen_tracker import (
    is_feedback_token, content_id_from_feedback_token, begin_listen_segment,
)
from src.utils.playback_user_events import consume_suppressed_playback_event

from src.webhooks.notification_webhook import mark_track_heard
from src.utils.queue_refill import maybe_refill_session_queue

import asyncio

logger = logging.getLogger(__name__)
FEEDBACK_TOKEN_PREFIX = "FEEDBACK_PROMPT:"


class PlaybackStartedHandler(AbstractRequestHandler):
    """Handles AudioPlayer.PlaybackStarted — records session start and sends analytics."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackStarted"

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
            existing = await resolve_playback_state(alexa_user_id, handler_input)
            if existing.get("state", {}).get("token") and existing["state"]["token"] != token:
                await flush_previous_track(alexa_user_id, None, handler_input)

            store = get_store(handler_input)
            track_id = store.get("playbackTrackId") or token

            try:
                mark_track_heard(track_id, alexa_user_id)
            except Exception:
                pass

            track_duration_ms = duration_ms_from_store(store)
            force_new = bool(store.get("forceNewPlaybackSession"))
            if force_new:
                update_store(handler_input, {"forceNewPlaybackSession": False})

            existing_state = existing.get("state") or {}
            session_id = existing_state.get("sessionId") \
                if (not force_new and existing_state.get("token") == token
                    and existing_state.get("sessionId")) \
                else f"{track_id}-{int(time.time() * 1000)}"

            now = int(time.time() * 1000)
            session_fields = {
                "token": token,
                "trackId": track_id,
                "sessionId": session_id,
                "startOffsetMs": offset_ms,
                "wallStart": now,
                "lastKnownOffsetMs": offset_ms,
                "lastKnownOffsetUpdatedAt": now,
                "trackDurationMs": track_duration_ms,
            }

            if track_duration_ms > 0 and not store.get("currentDurationSecs"):
                update_store(handler_input, {
                    "currentDurationSecs": track_duration_ms / 1000,
                    "playbackDurationEstimateMs": track_duration_ms,
                })

            play_start_patch = {"lastPlayTrackId": track_id}
            if store.get("lastPlayTrackId") != track_id or not store.get("lastPlayStartedAt"):
                play_start_patch["lastPlayStartedAt"] = now
            update_store(handler_input, play_start_patch)

            media = resolve_playback_event_media(store, session_fields)

            await save_playback_state(alexa_user_id, handler_input, {
                **session_fields,
                "currentAudioUrl": media.get("audioUrl"),
                "playbackSpeed": media.get("playbackSpeed"),
            })

            skip_started = consume_suppressed_playback_event(handler_input, "started")
            if not skip_started:
                try:
                    await send_playback_events({
                        "alexaUserId": alexa_user_id,
                        "handlerInput": handler_input,
                        "events": [
                            build_playback_event({
                                "sessionId": session_id,
                                "trackId": track_id,
                                "eventType": "AUDIO_PLAYER_PLAYBACK_STARTED",
                                "positionMs": offset_ms,
                                "trackDurationMs": track_duration_ms,
                                "eventLabel": "STARTED",
                                "timestamp": now,
                                "alexaTimestamp": alexa_timestamp_from_request(req),
                                **media,
                            }),
                        ],
                        "refreshTrackIds": [],
                    })
                except Exception:
                    pass

            begin_listen_segment(handler_input, {"token": token, "offsetMs": offset_ms})

            try:
                asyncio.ensure_future(maybe_refill_session_queue(handler_input, store))
            except Exception:
                pass

        return handler_input.response_builder.response
