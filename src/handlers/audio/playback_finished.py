"""
PlaybackFinishedHandler - Handles AudioPlayer.PlaybackFinished events.
Finalizes listen segments, sends analytics, and prompts for feedback.
"""
from __future__ import annotations

import logging
import time

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from config import settings

from src.services.persistence import (
    get_store, update_store, was_feedback_given, set_pending_feedback,
    mark_feedback_asked, dismiss_feedback_prompt, bump_queue_items_completed,
    peek_has_next_queue_item,
)
from src.services.alexa_api_client import send_playback_events, get_alexa_user_id
from src.services.alexa_reminders import has_reminder_permission, schedule_feedback_reminder_if_needed
from src.utils.skill_request import get_request_type
from src.utils.speech import ssml, FEEDBACK_AFTER_TRACK, FEEDBACK_AWAITING_REPROMPT
from src.utils.playback_event_builder import (
    build_playback_event, resolve_playback_event_media, alexa_timestamp_from_request,
)
from src.utils.playback_timing import resolve_finished_event_timing
from src.utils.playback_session import resolve_playback_state, clear_all_playback_state
from src.utils.listen_tracker import (
    is_feedback_token, finalize_listen_segment, build_fallback_finished_entry,
    record_finished_listen_from_timing, persist_last_completed_listen,
    build_synthetic_playback_state, record_force_finished_listen,
)
from src.utils.listen_log import summarize_listen_ms
from src.handlers.audio.playback_nearly_finished import _try_enqueue_session_queue_content
from src.utils.content_playback import is_finished_token_last_in_session

logger = logging.getLogger(__name__)


def _is_wrapper_or_outro_token(token: str) -> bool:
    """Check if a token belongs to a wrapper/outro audio segment."""
    if not token:
        return False
    return isinstance(token, str) and (token.startswith("wrapper-") or token.startswith("outro-"))


async def _resolve_duration_secs_for_finish(store, token):
    """Try multiple strategies to resolve the track duration in seconds."""
    if isinstance(store.get("currentDurationSecs"), (int, float)) and store.get("currentDurationSecs", 0) > 0:
        return store["currentDurationSecs"]

    tracks = store.get("currentTracks") or []
    idx = store.get("currentTrackIndex", 0)
    if idx < len(tracks):
        tr = tracks[idx]
        if tr and isinstance(tr.get("durationSecs"), (int, float)) and tr["durationSecs"] > 0:
            return tr["durationSecs"]

    for tr in tracks:
        if not tr or not tr.get("id"):
            continue
        if tr["id"] == token or tr["id"] == store.get("playbackTrackId"):
            if isinstance(tr.get("durationSecs"), (int, float)) and tr["durationSecs"] > 0:
                return tr["durationSecs"]

    return None


class PlaybackFinishedHandler(AbstractRequestHandler):
    """Handles AudioPlayer.PlaybackFinished — records completion and prompts for feedback."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackFinished"

    async def handle(self, handler_input: HandlerInput):
        req = handler_input.request_envelope.request
        token = req.token
        offset_ms = req.offset_in_milliseconds or 0
        set_feedback = False

        if not is_feedback_token(token) and not _is_wrapper_or_outro_token(token):
            alexa_user_id = get_alexa_user_id(handler_input)
            resolved = await resolve_playback_state(alexa_user_id, handler_input)
            source = resolved.get("source")
            state = resolved.get("state")
            store = get_store(handler_input)

            effective_state = (state if (state and state.get("trackId") and state.get("sessionId"))
                               else build_synthetic_playback_state(store, token))
            now = int(time.time() * 1000)
            finished_timing = None

            duration_secs = await _resolve_duration_secs_for_finish(store, token)
            if duration_secs and duration_secs > 0 and not store.get("currentDurationSecs"):
                update_store(handler_input, {
                    "currentDurationSecs": duration_secs,
                    "playbackDurationEstimateMs": round(duration_secs * 1000),
                })
                store = get_store(handler_input)

            if effective_state and effective_state.get("trackId"):
                finished_timing = resolve_finished_event_timing(effective_state, store, offset_ms)

                if effective_state.get("sessionId"):
                    store_now = get_store(handler_input)
                    media = resolve_playback_event_media(store_now, effective_state)
                    try:
                        await send_playback_events({
                            "alexaUserId": alexa_user_id,
                            "handlerInput": handler_input,
                            "events": [
                                build_playback_event({
                                    "sessionId": effective_state["sessionId"],
                                    "trackId": effective_state["trackId"],
                                    "eventType": "AUDIO_PLAYER_PLAYBACK_FINISHED",
                                    "positionMs": finished_timing["positionMs"],
                                    "trackDurationMs": finished_timing["trackDurationMs"],
                                    "eventLabel": "FINISHED",
                                    "timestamp": now,
                                    "alexaTimestamp": alexa_timestamp_from_request(req),
                                    **media,
                                }),
                            ],
                            "refreshTrackIds": [effective_state["trackId"]],
                        })
                    except Exception:
                        pass

                store_before_fb = get_store(handler_input)
                finished_track_id = effective_state["trackId"] or token
                already_rated = was_feedback_given(
                    store_before_fb, token, finished_track_id,
                    store_before_fb.get("feedbackContentId"),
                    store_before_fb.get("playbackTrackId"),
                    store_before_fb.get("currentContentId"),
                )
                if not already_rated:
                    set_pending_feedback(handler_input, {"trackId": token})
                    mark_feedback_asked(handler_input, token)
                    set_feedback = True

                logger.info(
                    "Hear: playback event time spent trackId=%s eventType=AUDIO_PLAYER_PLAYBACK_FINISHED stateSource=%s",
                    effective_state["trackId"], source,
                )

            entry = finalize_listen_segment(handler_input, {
                "offsetMs": offset_ms, "reason": "finished", "token": token,
            })
            if not entry:
                entry = build_fallback_finished_entry(handler_input, token, offset_ms)
            if not entry and finished_timing:
                entry = record_finished_listen_from_timing(handler_input, {
                    "token": token,
                    "trackId": (effective_state or {}).get("trackId") if effective_state else None,
                    "sessionId": (effective_state or {}).get("sessionId") if effective_state else None,
                    "positionMs": finished_timing["positionMs"],
                    "trackDurationMs": finished_timing["trackDurationMs"],
                    "store": get_store(handler_input),
                })
            if not entry or not entry.get("listenedMs"):
                entry = record_force_finished_listen(handler_input, {
                    "token": token,
                    "store": get_store(handler_input),
                    "durationSecs": store.get("currentDurationSecs") or duration_secs,
                    "offsetMs": offset_ms,
                })

            if entry and entry.get("listenedMs"):
                persist_last_completed_listen(handler_input, entry)
                update_store(handler_input, {"lastOffsetMs": entry["listenedMs"]})

            await clear_all_playback_state(alexa_user_id, handler_input)

            try:
                final_track = is_finished_token_last_in_session(store, token)
                if final_track and (store.get("upcomingQueue") or []):
                    bump_queue_items_completed(handler_input)
                after_bump = get_store(handler_input)
                has_next = peek_has_next_queue_item(after_bump)
                if final_track and not has_next and not after_bump.get("awaitingStillListening"):
                    update_store(handler_input, {"showHomeBrowseOnNextLaunch": True})
                if final_track and has_next and not set_feedback:
                    session_next = await _try_enqueue_session_queue_content(handler_input, token)
                    if session_next and session_next.get("directive"):
                        return handler_input.response_builder \
                            .add_directive(session_next["directive"]) \
                            .response

                after = get_store(handler_input)
                if after.get("awaitingFeedback") and settings.HEAR_FEEDBACK_REMINDER \
                        and not after.get("feedbackReminderAlertToken"):
                    try:
                        if has_reminder_permission(handler_input):
                            await schedule_feedback_reminder_if_needed(handler_input, {
                                "remainingMs": settings.HEAR_FEEDBACK_NEARLY_BUFFER_MS,
                            })
                    except Exception:
                        pass
            except Exception:
                pass

        if set_feedback:
            fb_store = get_store(handler_input)
            title = fb_store.get("feedbackContentTitle") or "that track"
            creator = fb_store.get("feedbackCreator") or "the creator"
            return handler_input.response_builder \
                .speak(ssml(FEEDBACK_AFTER_TRACK(title, creator))) \
                .reprompt(ssml(FEEDBACK_AWAITING_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        return handler_input.response_builder.response
