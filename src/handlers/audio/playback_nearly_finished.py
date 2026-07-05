"""
PlaybackNearlyFinishedHandler - Pre-fetches the next track before the current one ends.
Also sends PlaybackNearlyFinished analytics and handles multi-track publication advancement.
"""
from __future__ import annotations

import logging
import time

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from config import settings

from src.services.persistence import get_store, update_store
from src.services.alexa_api_client import send_playback_events, get_alexa_user_id
from src.services.flush_previous_track import flush_previous_track
from src.utils.skill_request import get_request_type
from src.utils.audio import build_play_directive, build_content_metadata
from src.utils.playback_event_builder import (
    build_playback_event, resolve_playback_event_media, alexa_timestamp_from_request,
)
from src.utils.playback_timing import resolve_playback_event_timing, playback_state_duration_patch
from src.utils.playback_session import resolve_playback_state, save_playback_state
from src.utils.listen_tracker import is_feedback_token, finalize_listen_segment, begin_listen_segment
from src.utils.content_playback import has_queued_tracks, queue_parent_for_token_fallback
from src.utils.publication_tracks import has_more_publication_tracks, resolve_publication_track_at_index
from src.utils.playback_start import prepare_playback_audio_and_store
from src.utils.queue_refill import maybe_refill_session_queue
from src.utils.session_queue import resolve_queue_item_for_playback

logger = logging.getLogger(__name__)


def _is_wrapper_or_outro_token(token: str) -> bool:
    """Check if a token belongs to a wrapper/outro audio segment."""
    if not token:
        return False
    return isinstance(token, str) and (token.startswith("wrapper-") or token.startswith("outro-"))


async def _try_enqueue_session_queue_content(handler_input: HandlerInput, token: str):
    """Try to enqueue the next item from the session queue for nearly-finished preloading."""
    store = get_store(handler_input)
    queue = store.get("upcomingQueue") or []
    if not queue:
        return None

    try:
        await maybe_refill_session_queue(handler_input, get_store(handler_input))
    except Exception:
        pass

    store = get_store(handler_input)
    queue = store.get("upcomingQueue") or []
    q_idx = store.get("queueIndex", 0)
    next_idx = q_idx + 1
    if next_idx >= len(queue):
        return None

    interval = settings.HEAR_STILL_LISTENING_INTERVAL
    completed = store.get("queueItemsCompleted", 0)
    if interval > 0 and completed > 0 and completed % interval == 0:
        update_store(handler_input, {
            "awaitingStillListening": True,
            "awaitingContinueAfterFlag": True,
        })
        return None

    raw = queue[next_idx]
    try:
        content = await resolve_queue_item_for_playback(raw)
    except Exception:
        content = None
    if not content:
        return None

    update_store(handler_input, {"queueIndex": next_idx})
    prepared = prepare_playback_audio_and_store(handler_input, content, 0)
    if not prepared:
        update_store(handler_input, {"queueIndex": q_idx})
        return None

    track_info = prepared["trackInfo"]
    audio_url = prepared["audioUrl"]
    return {
        "directive": build_play_directive({
            "url": audio_url,
            "token": track_info["token"],
            "prevToken": token,
            "metadata": build_content_metadata(
                content, track_info.get("trackTitle"), track_info.get("effectiveCategory"),
            ),
            "handlerInput": handler_input,
        }),
    }


class PlaybackNearlyFinishedHandler(AbstractRequestHandler):
    """Handles AudioPlayer.PlaybackNearlyFinished — pre-fetches next track."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackNearlyFinished"

    async def handle(self, handler_input: HandlerInput):
        req = handler_input.request_envelope.request
        token = req.token
        offset_ms = req.offset_in_milliseconds or 0

        if is_feedback_token(token) or _is_wrapper_or_outro_token(token):
            return handler_input.response_builder.response

        store = get_store(handler_input)
        alexa_user_id = get_alexa_user_id(handler_input)

        if isinstance(offset_ms, (int, float)) and offset_ms >= 0:
            store_now = get_store(handler_input)
            offset_patch = {"lastOffsetMs": offset_ms, "lastToken": token}
            if offset_ms > 0:
                offset_patch["playbackDurationEstimateMs"] = max(
                    store_now.get("playbackDurationEstimateMs") or 0, offset_ms,
                )
            update_store(handler_input, offset_patch)

            resolved = await resolve_playback_state(alexa_user_id, handler_input)
            playback_state = resolved.get("state")
            if playback_state:
                await save_playback_state(alexa_user_id, handler_input, {
                    **playback_state,
                    "lastKnownOffsetMs": offset_ms,
                    "lastKnownOffsetUpdatedAt": int(time.time() * 1000),
                    **playback_state_duration_patch(playback_state, store_now, offset_ms),
                })

        resolved = await resolve_playback_state(alexa_user_id, handler_input)
        playback_state = resolved.get("state")
        if playback_state and playback_state.get("trackId") and playback_state.get("sessionId"):
            now = int(time.time() * 1000)
            store_now = get_store(handler_input)
            result = resolve_playback_event_timing({
                "state": playback_state,
                "store": store_now,
                "positionMs": offset_ms,
            })
            position_ms = result.get("positionMs")
            track_duration_ms = result.get("trackDurationMs")
            media = resolve_playback_event_media(store_now, playback_state)
            try:
                await send_playback_events({
                    "alexaUserId": alexa_user_id,
                    "handlerInput": handler_input,
                    "events": [
                        build_playback_event({
                            "sessionId": playback_state["sessionId"],
                            "trackId": playback_state["trackId"],
                            "eventType": "AUDIO_PLAYER_PLAYBACK_NEARLY_FINISHED",
                            "positionMs": position_ms,
                            "trackDurationMs": track_duration_ms,
                            "eventLabel": "NEARLYFINISHED",
                            "timestamp": now,
                            "alexaTimestamp": alexa_timestamp_from_request(req),
                            **media,
                        }),
                    ],
                    "refreshTrackIds": [playback_state["trackId"]],
                })
            except Exception:
                pass

        if has_more_publication_tracks(store):
            next_index = (store.get("currentTrackIndex", 0)) + 1
            resolved_track = await resolve_publication_track_at_index(handler_input, store, next_index)
            if resolved_track and resolved_track.get("track", {}).get("audioUrl"):
                await flush_previous_track(alexa_user_id, offset_ms, handler_input)
                finalize_listen_segment(handler_input, {
                    "offsetMs": offset_ms, "reason": "track_advance", "token": token,
                })

                track = resolved_track["track"]
                qp = queue_parent_for_token_fallback(store)
                next_token = track.get("id") or f"{qp}:{next_index}"
                track_duration = track.get("durationSecs") \
                    if isinstance(track.get("durationSecs"), (int, float)) \
                    else store.get("currentDurationSecs")
                update_store(handler_input, {
                    "currentTrackIndex": next_index,
                    "feedbackContentId": next_token,
                    "playbackTrackId": track.get("id"),
                    "feedbackCategory": track.get("category") or store.get("feedbackCategory"),
                    "feedbackContentTitle": track.get("title"),
                    "feedbackCreator": track.get("creator") or store.get("feedbackCreator"),
                    "currentTotalTracks": resolved_track.get("total"),
                    "currentDurationSecs": track_duration,
                })
                begin_listen_segment(handler_input, {"token": next_token, "offsetMs": 0})

                return handler_input.response_builder \
                    .add_directive(build_play_directive({
                        "url": track["audioUrl"],
                        "token": next_token,
                        "prevToken": token,
                        "metadata": {
                            "title": track.get("title", ""),
                            "subtitle": store.get("feedbackContentTitle", ""),
                        },
                        "progressReport": True,
                        "durationSecs": track.get("durationSecs")
                        if isinstance(track.get("durationSecs"), (int, float))
                        else store.get("currentDurationSecs"),
                        "handlerInput": handler_input,
                    })) \
                    .response

        if has_queued_tracks(store):
            update_store(handler_input, {
                "currentPublicationId": None,
                "playbackParentId": None,
                "playbackContentType": None,
                "currentTrackIndex": 0,
                "currentTotalTracks": 0,
                "currentTracks": [],
            })

        store = get_store(handler_input)
        session_next = await _try_enqueue_session_queue_content(handler_input, token)
        if session_next and session_next.get("directive"):
            handler_input.response_builder.add_directive(session_next["directive"])

        return handler_input.response_builder.response
