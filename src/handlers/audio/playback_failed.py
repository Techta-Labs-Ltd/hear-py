from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.services.persistence import get_store, update_store
from src.services.api import search
from src.utils.skill_request import get_request_type
from src.utils.speech import ssml, PLAYBACK_FAILED, NO_CONTENT_AVAILABLE
from src.utils.audio import resolve_track_audio, build_play_directive, build_content_metadata
from src.utils.content_playback import queue_parent_for_token_fallback
from src.utils.listen_tracker import finalize_listen_segment, schedule_playback_finished
from src.utils.session_queue import resolve_queue_item_for_playback
from src.utils.playback_start import prepare_playback_audio_and_store

logger = logging.getLogger(__name__)


def _is_wrapper_or_outro_token(token: str) -> bool:
    """Check if a token belongs to a wrapper/outro audio segment."""
    if not token:
        return False
    return str(token).startswith("wrapper-") or str(token).startswith("outro-")


class PlaybackFailedHandler(AbstractRequestHandler):
    """Handles AudioPlayer.PlaybackFailed — recovers with fallback content."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackFailed"

    async def handle(self, handler_input: HandlerInput):
        req = handler_input.request_envelope.request
        error = req.error
        token = req.token
        logger.error("PlaybackFailed: error=%s token=%s", error, token)

        if _is_wrapper_or_outro_token(token):
            logger.warning("Hear: wrapper/outro audio failed, skipping token=%s", token)
            wo_store = get_store(handler_input)
            queue = wo_store.get("upcomingQueue") or []
            if queue:
                idx = wo_store.get("queueIndex", 0)
                next_idx = idx + 1
                if next_idx < len(queue):
                    try:
                        raw = queue[next_idx]
                        content = await resolve_queue_item_for_playback(raw)
                        if content:
                            update_store(handler_input, {"queueIndex": next_idx})
                            prepared = prepare_playback_audio_and_store(handler_input, content, 0)
                            if prepared:
                                return handler_input.response_builder \
                                    .add_directive(build_play_directive({
                                        "url": prepared["audioUrl"],
                                        "token": prepared["trackInfo"]["token"],
                                        "metadata": build_content_metadata(
                                            content, prepared["trackInfo"].get("trackTitle"),
                                            prepared["trackInfo"].get("effectiveCategory"),
                                        ),
                                        "handlerInput": handler_input,
                                    })) \
                                    .response
                    except Exception as err:
                        logger.warning("Failed recovery after wrapper fail: %s", err)
            return handler_input.response_builder.response

        store = get_store(handler_input)
        failed_entry = finalize_listen_segment(handler_input, {
            "offsetMs": store.get("lastOffsetMs", 0),
            "reason": "failed",
        })
        if failed_entry:
            schedule_playback_finished(handler_input, failed_entry)

        try:
            exclude_ids = {x for x in [token, store.get("feedbackContentId"),
                                       queue_parent_for_token_fallback(store)] if x}
            result = await search({"intent": "general", "q": "", "limit": 5, "page": 0})
            items = [
                i for i in (result.get("results") or [])
                if i and i.get("id") and i["id"] not in exclude_ids
            ]
            skip_parent_id = queue_parent_for_token_fallback(store)
            next_item = None
            for item in items:
                if (skip_parent_id is None or item.get("id") != skip_parent_id) \
                        and item.get("id") != token \
                        and item.get("id") != store.get("feedbackContentId"):
                    next_item = item
                    break
            if not next_item and items:
                next_item = items[0]

            if next_item:
                track_info = resolve_track_audio(next_item)
                update_store(handler_input, {
                    "feedbackContentId": track_info.get("trackId") or next_item.get("id"),
                    "currentContentId": track_info.get("trackId") or next_item.get("id"),
                    "currentContentTitle": next_item.get("title"),
                    "currentCreator": next_item.get("creator"),
                    "currentCreatorId": next_item.get("creatorId"),
                    "currentCategory": track_info.get("effectiveCategory"),
                    "playbackTrackId": track_info.get("trackId"),
                    "feedbackCategory": track_info.get("effectiveCategory"),
                    "feedbackCreator": next_item.get("creator"),
                    "feedbackCreatorId": next_item.get("creatorId"),
                    "feedbackContentTitle": next_item.get("title"),
                    "playbackParentId": track_info.get("playbackParentId"),
                    "playbackContentType": track_info.get("contentType"),
                    "currentPublicationId": track_info.get("playbackParentId") if track_info.get("isMultiTrack") else None,
                    "currentTrackIndex": track_info.get("trackIndex"),
                    "currentTracks": next_item.get("tracks", []) if track_info.get("isMultiTrack") else [],
                })

                return handler_input.response_builder \
                    .speak(ssml(PLAYBACK_FAILED)) \
                    .add_directive(build_play_directive({
                        "url": track_info["audioUrl"],
                        "token": track_info["token"],
                        "metadata": build_content_metadata(
                            next_item, track_info.get("trackTitle"),
                            track_info.get("effectiveCategory"),
                        ),
                        "handlerInput": handler_input,
                    })) \
                    .response
        except Exception as err:
            logger.error("PlaybackFailed recovery failed: %s", err)

        return handler_input.response_builder \
            .speak(ssml(NO_CONTENT_AVAILABLE)) \
            .response
