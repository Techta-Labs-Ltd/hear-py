from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.utils.request_util import get_slot_value

from config import settings

from src.services.persistence import (
    get_store, update_store, append_to_queue, init_queue, set_browse_catalog,
    get_browse_catalog, record_listening_event, clear_queue,
    reset_queue_items_completed, bump_queue_items_completed, peek_has_next_queue_item,
)
from src.services.api import search
from src.services.alexa_api_client import get_alexa_user_id
from src.services.flush_previous_track import flush_previous_track
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import (
    ssml, PLAYBACK_SPEED_SET, PLAYBACK_SPEED_FALLBACK_DEFAULT,
    PLAYBACK_SPEED_MAX, PLAYBACK_SPEED_MIN, PLAYBACK_SPEED_NOT_SUPPORTED,
    PLAYBACK_SPEED_INVALID, PLAYBACK_SPEED_UNAVAILABLE, NOTHING_TO_RESUME, RESUMING,
    NO_CONTENT_AVAILABLE, CANNOT_SEEK, REWOUND, FAST_FORWARDED, REPLAYING,
    PLAYING_PREVIOUS, NO_PREVIOUS, WELCOME_REPROMPT, TRACK_PLAYING, CONTENT_NOT_READY,
    REPROMPT_NO_CITY, LOCAL_CONTENT_FALLBACK, ERROR_GENERIC, GOODBYE,
)
from src.utils.audio import (
    build_play_directive, build_stop_directive, build_content_metadata,
    normalise_speed, resolve_seek_ms, resolve_track_audio, find_speed_url,
    get_next_speed, resolve_audio_url_for_speed, resolve_effective_playback_speed,
    strip_speed_from_url,
)
from src.utils.playback_session import (
    clear_all_playback_state, resolve_playback_state, save_playback_state,
)
from src.utils.playback_context import (
    read_audio_player_context, resolve_active_playback_token, is_audio_player_active,
)
from src.utils.listen_tracker import close_listen_segment
from src.utils.feedback_gate import block_if_awaiting_feedback, enforce_interaction_gate
from src.utils.content_playback import (
    has_queued_tracks, queue_parent_for_token_fallback,
    is_finished_token_last_in_session,
)
from src.utils.publication_tracks import (
    has_more_publication_tracks, resolve_publication_track_at_index,
)
from src.utils.next_content import (
    build_playback_exclude_set, pick_next_search_item,
    record_current_playback_for_skip,
)
from src.utils.browse_catalog import (
    build_catalog_from_search_result, catalog_search_context, has_more_server_pages,
)
from src.utils.browse_navigation import (
    play_next_in_browse_session, play_previous_in_browse_session,
)
from src.utils.search_filters import SearchPayload
from src.utils.lambda_deadline import (
    compute_search_timeout_ms, has_budget_for_api,
)
from src.utils.normalize_content_item import (
    content_title_for_speech, pick_content_credit, normalize_content_items,
)
from src.utils.session_queue import clone_queue_item, resolve_queue_item_for_playback
from src.utils.playback_user_events import emit_user_playback_event, USER_PLAYBACK_EVENT_TYPES
from src.utils.playback_start import start_playback

logger = logging.getLogger(__name__)

PLAYBACK_CONTROLLER = {
    "PAUSE": "PlaybackController.PauseCommandIssued",
    "PLAY": "PlaybackController.PlayCommandIssued",
    "NEXT": "PlaybackController.NextCommandIssued",
    "PREVIOUS": "PlaybackController.PreviousCommandIssued",
}


def _gate_pending_feedback(handler_input: HandlerInput):
    """Apply both feedback gate and interaction gate checks."""
    return block_if_awaiting_feedback(handler_input) or enforce_interaction_gate(handler_input)


def _url_at_store_speed(store: Dict[str, Any], audio_url: str, track_speed_variants=None):
    """Resolve the audio URL at the user's current preferred playback speed."""
    variants = track_speed_variants or store.get("currentPlaybackSpeeds")
    effective_speed = resolve_effective_playback_speed(
        store.get("playbackSpeed", settings.default_speed), variants,
    )
    return resolve_audio_url_for_speed(audio_url, effective_speed, variants)


def _speed_change_ack_speech(requested_speed, variants):
    """Build the spoken confirmation message for a speed change."""
    effective_speed = resolve_effective_playback_speed(requested_speed, variants)
    if requested_speed != settings.default_speed and effective_speed == settings.default_speed:
        return PLAYBACK_SPEED_FALLBACK_DEFAULT(requested_speed)
    spoken = settings.default_speed if effective_speed == settings.default_speed else requested_speed
    return PLAYBACK_SPEED_SET(spoken)


async def _resolve_resume_playback(store: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Attempt to resolve playback media details for a resume operation from locally stored data."""
    resume_token = resolve_active_playback_token(store)
    tracks = store.get("currentTracks") or []
    track_idx = store.get("currentTrackIndex", 0)
    track = tracks[track_idx] if track_idx < len(tracks) and tracks else None

    if track and track.get("audioUrl"):
        token = track.get("id") or resume_token or store.get("lastToken")
        return {
            "audioUrl": track["audioUrl"],
            "token": token,
            "metadata": {
                "title": track.get("title") or store.get("currentContentTitle") or store.get("feedbackContentTitle") or "Hear",
                "subtitle": store.get("feedbackContentTitle") or "",
            },
        }

    audio_url = store.get("lastAudioUrl")
    token = resume_token or store.get("lastToken")
    if not audio_url or not token:
        return None
    return {
        "audioUrl": audio_url,
        "token": token,
        "metadata": {
            "title": store.get("currentContentTitle") or store.get("feedbackContentTitle") or "Hear",
            "subtitle": store.get("feedbackContentTitle") or "",
        },
    }


def _resolve_local_playback_media(handler_input: HandlerInput, store: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resolve local playback media (URL, token, offset) from store and audio context."""
    audio_ctx = read_audio_player_context(handler_input)
    token = (audio_ctx.get("token") if audio_ctx else None) or resolve_active_playback_token(store)
    if not token:
        return None

    offset_ms = (audio_ctx.get("offsetMs") if audio_ctx and isinstance(audio_ctx.get("offsetMs"), (int, float))
                 else None) or store.get("lastOffsetMs", 0)

    audio_url = None
    metadata = None

    if has_queued_tracks(store):
        tracks = store.get("currentTracks", [])
        idx = store.get("currentTrackIndex", 0)
        if idx < len(tracks):
            track = tracks[idx]
            if track.get("audioUrl"):
                audio_url = track["audioUrl"]
                metadata = {
                    "title": track.get("title") or store.get("feedbackContentTitle") or "Hear",
                    "subtitle": store.get("feedbackContentTitle") or "",
                }

    if not audio_url and store.get("currentAudioUrl"):
        audio_url = strip_speed_from_url(store["currentAudioUrl"])
    if not audio_url and store.get("playbackSession", {}).get("currentAudioUrl"):
        audio_url = strip_speed_from_url(store["playbackSession"]["currentAudioUrl"])

    if not metadata:
        title = store.get("feedbackContentTitle") or store.get("currentContentTitle")
        if title:
            metadata = build_content_metadata(
                {"title": title, "category": store.get("feedbackCategory") or store.get("currentCategory"),
                 "tags": []},
                title, store.get("feedbackCategory") or store.get("currentCategory"),
            )

    if not audio_url:
        return None
    return {"audioUrl": audio_url, "token": token, "offsetMs": offset_ms, "metadata": metadata}


async def _restart_current_playback_at_speed(
    handler_input: HandlerInput, requested_speed, speed_url=None,
):
    """Restart the current playing content at a new playback speed."""
    store = get_store(handler_input)
    active_token = (read_audio_player_context(handler_input) or {}).get("token") \
        or resolve_active_playback_token(store)
    if not active_token:
        return None

    media = _resolve_local_playback_media(handler_input, store)
    if not media or not media.get("audioUrl"):
        try:
            resolved = await _resolve_resume_playback(store)
            if resolved and resolved.get("audioUrl"):
                media = {
                    "audioUrl": resolved["audioUrl"],
                    "token": resolved["token"],
                    "offsetMs": store.get("lastOffsetMs", 0),
                    "metadata": resolved["metadata"],
                }
        except Exception as err:
            logger.warning("resolveResumePlayback failed during speed change: %s", err)

    if not media or not media.get("audioUrl"):
        return None

    tracks = store.get("currentTracks", [])
    idx = store.get("currentTrackIndex", 0)
    track = tracks[idx] if idx < len(tracks) else None
    variants = (track.get("playback_speed") if track else None) or store.get("currentPlaybackSpeeds")
    variant_url = speed_url or find_speed_url(variants, requested_speed)
    final_url = variant_url or resolve_audio_url_for_speed(
        media["audioUrl"], requested_speed, variants,
    )
    if not final_url:
        final_url = strip_speed_from_url(media["audioUrl"]) or media["audioUrl"]

    update_store(handler_input, {
        "playbackSpeed": requested_speed,
        "lastOffsetMs": media["offsetMs"],
        "lastToken": media["token"],
    })

    return handler_input.response_builder \
        .speak(ssml(_speed_change_ack_speech(requested_speed, variants))) \
        .add_directive(build_play_directive({
            "url": final_url,
            "token": media["token"],
            "offsetMs": media["offsetMs"],
            "metadata": media["metadata"],
            "progressReport": True,
            "durationSecs": store.get("currentDurationSecs"),
            "handlerInput": handler_input,
        })) \
        .response


async def _handle_relative_speed_step(handler_input: HandlerInput, direction: str):
    """Handle incremental speed up/down with bounds checking."""
    gated = _gate_pending_feedback(handler_input)
    if gated:
        return gated

    store = get_store(handler_input)
    current_speeds = store.get("currentPlaybackSpeeds")
    current_speed = store.get("playbackSpeed", settings.default_speed)

    if current_speeds and current_speeds:
        next_speed = get_next_speed(current_speeds, current_speed, direction)
        if not next_speed:
            msg = PLAYBACK_SPEED_MAX if direction == "up" else PLAYBACK_SPEED_MIN
            return handler_input.response_builder \
                .speak(ssml(msg)) \
                .reprompt(WELCOME_REPROMPT) \
                .set_should_end_session(False) \
                .response

        update_store(handler_input, {"playbackSpeed": next_speed["speed"]})
        try:
            url_key = next_speed.get("audioUrl")
            restarted = await _restart_current_playback_at_speed(
                handler_input, next_speed["speed"], url_key,
            )
            if restarted:
                return restarted
        except Exception as err:
            logger.warning("Relative speed restart failed: %s", err)

        return handler_input.response_builder \
            .speak(ssml(PLAYBACK_SPEED_SET(next_speed["speed"]))) \
            .response

    if not store.get("lastToken"):
        return handler_input.response_builder \
            .speak(ssml(PLAYBACK_SPEED_NOT_SUPPORTED)) \
            .reprompt(WELCOME_REPROMPT) \
            .set_should_end_session(False) \
            .response

    return handler_input.response_builder \
        .speak(ssml(PLAYBACK_SPEED_NOT_SUPPORTED)) \
        .reprompt(WELCOME_REPROMPT) \
        .set_should_end_session(False) \
        .response


async def _advance_publication_track(handler_input: HandlerInput, store: Dict[str, Any], next_index: int):
    """Advance to the next track within a multi-track publication."""
    resolved = await resolve_publication_track_at_index(handler_input, store, next_index)
    if not resolved or not resolved.get("track", {}).get("audioUrl"):
        return None

    queue_parent = queue_parent_for_token_fallback(store)
    track = resolved["track"]
    total = resolved["total"]
    token = track.get("id") or f"{queue_parent}:{next_index}"

    update_store(handler_input, {
        "currentTrackIndex": next_index,
        "lastOffsetMs": 0,
        "feedbackContentId": token,
        "playbackTrackId": track.get("id"),
        "feedbackCategory": track.get("category") or store.get("feedbackCategory"),
        "currentTotalTracks": total,
        "currentDurationSecs": track.get("durationSecs")
        if isinstance(track.get("durationSecs"), (int, float))
        else store.get("currentDurationSecs"),
    })

    play_url = _url_at_store_speed(
        get_store(handler_input), track["audioUrl"], track.get("playback_speed"),
    )
    return {"playUrl": play_url, "token": token, "track": track, "total": total}


def _clear_queued_playback_patch() -> Dict[str, Any]:
    """Return a store patch that clears queued playback state."""
    return {
        "currentPublicationId": None,
        "playbackParentId": None,
        "playbackContentType": None,
        "currentTrackIndex": 0,
        "currentTotalTracks": 0,
        "currentTracks": [],
    }


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


class SetPlaybackSpeedHandler(AbstractRequestHandler):
    """Sets the playback speed to an exact value (e.g. 1.5x)."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "SetPlaybackSpeedIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        gated = _gate_pending_feedback(handler_input)
        if gated:
            return gated

        store = get_store(handler_input)
        current_speeds = store.get("currentPlaybackSpeeds")

        try:
            speed_raw = get_slot_value(handler_input, "speed")
        except Exception:
            slots = handler_input.request_envelope.request.intent.slots if \
                hasattr(handler_input.request_envelope.request, "intent") else {}
            slot = slots.get("speed") if slots else None
            speed_raw = slot.value if slot and slot.value else None

        is_default = speed_raw is None or str(speed_raw).strip() == ""
        if is_default:
            speed = settings.default_speed
        else:
            speed = normalise_speed(speed_raw)
            if not speed:
                return handler_input.response_builder \
                    .speak(PLAYBACK_SPEED_INVALID) \
                    .reprompt(PLAYBACK_SPEED_INVALID) \
                    .set_should_end_session(False) \
                    .response

        if is_default:
            update_store(handler_input, {"playbackSpeed": speed})
            if store.get("lastToken") or (read_audio_player_context(handler_input) or {}).get("token"):
                try:
                    restarted = await _restart_current_playback_at_speed(handler_input, speed)
                    if restarted:
                        return restarted
                except Exception as err:
                    logger.warning("SetPlaybackSpeed restart failed: %s", err)
            return handler_input.response_builder \
                .speak(ssml(PLAYBACK_SPEED_SET(speed))) \
                .reprompt(ssml("What would you like to listen to next?")) \
                .set_should_end_session(False) \
                .response

        if current_speeds and current_speeds:
            match = find_speed_url(current_speeds, speed)
            update_store(handler_input, {"playbackSpeed": speed})
            if resolve_active_playback_token(store) or (read_audio_player_context(handler_input) or {}).get("token"):
                try:
                    restarted = await _restart_current_playback_at_speed(handler_input, speed, match)
                    if restarted:
                        return restarted
                except Exception as err:
                    logger.warning("SetPlaybackSpeed restart failed: %s", err)
            if not match:
                available = ", ".join(f"{s.get('speed', '?')}x" for s in current_speeds)
                return handler_input.response_builder \
                    .speak(ssml(PLAYBACK_SPEED_UNAVAILABLE(speed, available))) \
                    .reprompt(WELCOME_REPROMPT) \
                    .set_should_end_session(False) \
                    .response
            return handler_input.response_builder \
                .speak(ssml(PLAYBACK_SPEED_SET(speed))) \
                .reprompt(ssml("What would you like to listen to next?")) \
                .set_should_end_session(False) \
                .response

        if resolve_active_playback_token(store) or (read_audio_player_context(handler_input) or {}).get("token"):
            update_store(handler_input, {"playbackSpeed": speed})
            try:
                restarted = await _restart_current_playback_at_speed(handler_input, speed)
                if restarted:
                    return restarted
            except Exception as err:
                logger.warning("SetPlaybackSpeed restart failed: %s", err)

        if not current_speeds or not current_speeds:
            return handler_input.response_builder \
                .speak(ssml(PLAYBACK_SPEED_NOT_SUPPORTED)) \
                .reprompt(WELCOME_REPROMPT) \
                .set_should_end_session(False) \
                .response


class IncreaseSpeedHandler(AbstractRequestHandler):
    """Increases playback speed by one step."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "IncreaseSpeedIntent"
        )

    def handle(self, handler_input: HandlerInput):
        return _handle_relative_speed_step(handler_input, "up")


class DecreaseSpeedHandler(AbstractRequestHandler):
    """Decreases playback speed by one step."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "DecreaseSpeedIntent"
        )

    def handle(self, handler_input: HandlerInput):
        return _handle_relative_speed_step(handler_input, "down")


class PauseIntentHandler(AbstractRequestHandler):
    """Handles pause/stop via voice or playback controller."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        rt = get_request_type(handler_input)
        return (
            rt == PLAYBACK_CONTROLLER["PAUSE"]
            or (rt == "IntentRequest"
                and get_intent_name(handler_input) in ("AMAZON.PauseIntent", "AMAZON.StopIntent"))
        )

    async def handle(self, handler_input: HandlerInput):
        gated = _gate_pending_feedback(handler_input)
        if gated:
            return gated

        try:
            intent_name = get_intent_name(handler_input)
            is_voice_stop = intent_name == "AMAZON.StopIntent"
            await emit_user_playback_event(handler_input, {
                "eventType": USER_PLAYBACK_EVENT_TYPES["USER_STOPPED"] if is_voice_stop
                else USER_PLAYBACK_EVENT_TYPES["PAUSED"],
                "eventLabel": "USERSTOPPED" if is_voice_stop else "PAUSED",
                "suppressFollowingStopped": True,
                "closeSegment": True,
            })
        except Exception:
            pass

        return handler_input.response_builder \
            .add_directive(build_stop_directive()) \
            .response


class ResumeIntentHandler(AbstractRequestHandler):
    """Handles resume via voice or playback controller."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        rt = get_request_type(handler_input)
        return (
            rt == PLAYBACK_CONTROLLER["PLAY"]
            or (rt == "IntentRequest"
                and get_intent_name(handler_input) == "AMAZON.ResumeIntent")
        )

    async def handle(self, handler_input: HandlerInput):
        gated = _gate_pending_feedback(handler_input)
        if gated:
            return gated

        store = get_store(handler_input)
        if not resolve_active_playback_token(store):
            return handler_input.response_builder \
                .speak(NOTHING_TO_RESUME) \
                .set_should_end_session(False) \
                .response

        try:
            audio_url = None
            metadata = {}
            token = resolve_active_playback_token(store)

            if has_queued_tracks(store):
                tracks = store.get("currentTracks", [])
                idx = store.get("currentTrackIndex", 0)
                if idx < len(tracks):
                    track = tracks[idx]
                    audio_url = track.get("audioUrl")
                    token = track.get("id") or f"{queue_parent_for_token_fallback(store)}:{idx}"
                    metadata = {"title": track.get("title", ""), "subtitle": store.get("feedbackContentTitle", "")}

            if not audio_url:
                resolved = await _resolve_resume_playback(store)
                if not resolved:
                    return handler_input.response_builder \
                        .speak(NO_CONTENT_AVAILABLE) \
                        .set_should_end_session(False) \
                        .response
                audio_url = resolved["audioUrl"]
                token = resolved["token"]
                metadata = resolved["metadata"]

            tracks = store.get("currentTracks", [])
            idx = store.get("currentTrackIndex", 0)
            track = tracks[idx] if idx < len(tracks) else None
            play_url = _url_at_store_speed(store, audio_url,
                                           track.get("playback_speed") if track else None)

            try:
                await emit_user_playback_event(handler_input, {
                    "eventType": USER_PLAYBACK_EVENT_TYPES["RESUMED"],
                    "eventLabel": "RESUMED",
                    "suppressFollowingStarted": True,
                })
            except Exception:
                pass

            return handler_input.response_builder \
                .speak(ssml(RESUMING)) \
                .add_directive(build_play_directive({
                    "url": play_url,
                    "token": token,
                    "offsetMs": store.get("lastOffsetMs"),
                    "metadata": metadata,
                    "handlerInput": handler_input,
                })) \
                .response
        except Exception:
            return handler_input.response_builder \
                .speak(NO_CONTENT_AVAILABLE) \
                .set_should_end_session(False) \
                .response


class NextIntentHandler(AbstractRequestHandler):
    """Handles next/skip via voice or playback controller."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        rt = get_request_type(handler_input)
        return (
            rt == PLAYBACK_CONTROLLER["NEXT"]
            or (rt == "IntentRequest"
                and get_intent_name(handler_input) == "AMAZON.NextIntent")
        )

    async def handle(self, handler_input: HandlerInput):
        gated = _gate_pending_feedback(handler_input)
        if gated:
            return gated

        store = get_store(handler_input)
        queue_parent = queue_parent_for_token_fallback(store)

        if store.get("feedbackCategory") or store.get("feedbackCreator"):
            record_listening_event(handler_input, {
                "category": store.get("feedbackCategory"),
                "creator": store.get("feedbackCreator"),
                "liked": False,
            })

        record_current_playback_for_skip(handler_input, store)

        if has_more_publication_tracks(store):
            next_index = (store.get("currentTrackIndex", 0)) + 1
            advanced = await _advance_publication_track(handler_input, store, next_index)
            if advanced:
                fresh_store = get_store(handler_input)
                return handler_input.response_builder \
                    .speak(ssml(TRACK_PLAYING(
                        next_index + 1, advanced["total"],
                        advanced["track"].get("title", ""),
                    ))) \
                    .add_directive(build_play_directive({
                        "url": advanced["playUrl"],
                        "token": advanced["token"],
                        "metadata": {
                            "title": advanced["track"].get("title", ""),
                            "subtitle": fresh_store.get("feedbackContentTitle", ""),
                        },
                        "handlerInput": handler_input,
                    })) \
                    .response

        if has_queued_tracks(store):
            update_store(handler_input, _clear_queued_playback_patch())

        browse_next = await play_next_in_browse_session(handler_input)
        if browse_next:
            return browse_next

        if not has_budget_for_api(handler_input):
            return handler_input.response_builder \
                .speak(NO_CONTENT_AVAILABLE) \
                .response

        store_after_catalog = get_store(handler_input)
        catalog = get_browse_catalog(store_after_catalog)
        exclude_set = build_playback_exclude_set(store_after_catalog, {"includeFutureQueue": False})
        skip_parent_id = queue_parent_for_token_fallback(store_after_catalog)

        ctx = catalog_search_context(catalog) if catalog else {"intent": "general", "q": ""}
        next_page = (catalog.get("currentPage", 0) + 1) if catalog and has_more_server_pages(catalog) else 0
        payload = SearchPayload.build(
            handler_input, store_after_catalog,
            q=ctx.get("q") or "",
            limit=settings.search_page_limit,
            page=next_page,
        )
        payload["filters"] = {
            **(payload.get("filters") or {}),
            "excludeIds": list(
                set((payload.get("filters", {}).get("excludeIds") or []) + list(exclude_set))
            )[:20],
        }

        result = await search(payload, timeout_ms=compute_search_timeout_ms(handler_input))
        items = result.get("results", []) if result else []
        next_item = pick_next_search_item(items, exclude_set, skip_parent_id)

        if not next_item:
            return handler_input.response_builder \
                .speak(NO_CONTENT_AVAILABLE) \
                .response

        if catalog and items and next_page > 0:
            merged = build_catalog_from_search_result(result, {
                **ctx,
                "page": next_page,
                "limit": catalog.get("limit") or settings.search_page_limit,
                "existingCatalog": catalog,
                "append": True,
            })
            set_browse_catalog(handler_input, merged, {"intent": catalog.get("intent")})

        fresh_items = [
            clone_queue_item(i) for i in normalize_content_items(items)
            if i.get("id") and str(i["id"]) not in exclude_set
        ]
        if fresh_items:
            append_to_queue(handler_input, fresh_items)

        return await start_playback(
            handler_input, next_item,
            LOCAL_CONTENT_FALLBACK(content_title_for_speech(next_item),
                                   pick_content_credit(next_item)),
            0, {"preserveSessionQueue": True},
        )


class PreviousIntentHandler(AbstractRequestHandler):
    """Handles previous via voice or playback controller."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        rt = get_request_type(handler_input)
        return (
            rt == PLAYBACK_CONTROLLER["PREVIOUS"]
            or (rt == "IntentRequest"
                and get_intent_name(handler_input) == "AMAZON.PreviousIntent")
        )

    async def handle(self, handler_input: HandlerInput):
        gated = _gate_pending_feedback(handler_input)
        if gated:
            return gated

        store = get_store(handler_input)
        queue_parent = queue_parent_for_token_fallback(store)

        if has_queued_tracks(store):
            prev_index = (store.get("currentTrackIndex", 0)) - 1
            if prev_index >= 0:
                tracks = store.get("currentTracks", [])
                track = tracks[prev_index]
                token = track.get("id") or f"{queue_parent}:{prev_index}"
                update_store(handler_input, {
                    "currentTrackIndex": prev_index,
                    "lastOffsetMs": 0,
                    "feedbackContentId": token,
                    "playbackTrackId": track.get("id"),
                    "feedbackCategory": track.get("category") or store.get("feedbackCategory"),
                })

                play_url = _url_at_store_speed(store, track.get("audioUrl"), track.get("playback_speed"))
                return handler_input.response_builder \
                    .speak(ssml(TRACK_PLAYING(prev_index + 1, len(tracks), track.get("title", "")))) \
                    .add_directive(build_play_directive({
                        "url": play_url,
                        "token": token,
                        "metadata": {"title": track.get("title", ""),
                                     "subtitle": store.get("feedbackContentTitle", "")},
                        "handlerInput": handler_input,
                    })) \
                    .response

        browse_prev = await play_previous_in_browse_session(handler_input)
        if browse_prev:
            return browse_prev

        history = [
            entry for entry in (store.get("playHistory") or [])
            if isinstance(entry, dict) and entry.get("audioUrl")
        ]

        if len(history) > 1:
            content = history[1]
            return await start_playback(
                handler_input, content,
                PLAYING_PREVIOUS(content.get("title", "")),
            )

        return handler_input.response_builder \
            .speak(NO_PREVIOUS) \
            .response


class RepeatIntentHandler(AbstractRequestHandler):
    """Restarts the current track from the beginning."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) in ("AMAZON.RepeatIntent", "AMAZON.StartOverIntent")
        )

    async def handle(self, handler_input: HandlerInput):
        store = get_store(handler_input)
        resume_token = resolve_active_playback_token(store)
        if not resume_token:
            return handler_input.response_builder \
                .speak(CANNOT_SEEK) \
                .response

        try:
            audio_url = None
            token = None
            metadata = None

            if has_queued_tracks(store):
                tracks = store.get("currentTracks", [])
                idx = store.get("currentTrackIndex", 0)
                track = tracks[idx] if idx < len(tracks) else None
                if track:
                    qp = queue_parent_for_token_fallback(store)
                    audio_url = track.get("audioUrl")
                    token = track.get("id") or f"{qp}:{idx}"
                    metadata = {"title": track.get("title", ""),
                                "subtitle": store.get("feedbackContentTitle", "")}
            else:
                resolved = await _resolve_resume_playback(store)
                if not resolved:
                    return handler_input.response_builder \
                        .speak(NO_CONTENT_AVAILABLE) \
                        .response
                audio_url = resolved["audioUrl"]
                token = resolved["token"]
                metadata = resolved["metadata"]

            alexa_user_id = get_alexa_user_id(handler_input)
            close_listen_segment(handler_input, {"offsetMs": store.get("lastOffsetMs", 0)})
            if alexa_user_id:
                await flush_previous_track(alexa_user_id, store.get("lastOffsetMs", 0), handler_input)

            update_store(handler_input, {
                "lastOffsetMs": 0,
                "lastToken": token,
                "playbackTrackId": token,
                "forceNewPlaybackSession": True,
                "playbackSession": None,
            })

            tracks = store.get("currentTracks", [])
            idx = store.get("currentTrackIndex", 0)
            track = tracks[idx] if idx < len(tracks) else None
            play_url = _url_at_store_speed(store, audio_url,
                                           track.get("playback_speed") if track else None)

            return handler_input.response_builder \
                .speak(ssml(REPLAYING)) \
                .add_directive(build_play_directive({
                    "url": play_url, "token": token, "offsetMs": 0,
                    "metadata": metadata, "handlerInput": handler_input,
                })) \
                .response
        except Exception:
            return handler_input.response_builder \
                .speak(NO_CONTENT_AVAILABLE) \
                .response


class RewindIntentHandler(AbstractRequestHandler):
    """Rewinds the current track by a configurable step."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "RewindIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        gated = _gate_pending_feedback(handler_input)
        if gated:
            return gated

        store = get_store(handler_input)
        if not resolve_active_playback_token(store):
            return handler_input.response_builder \
                .speak(CANNOT_SEEK) \
                .response

        seek_ms = resolve_seek_ms(handler_input)
        new_offset = max(0, (store.get("lastOffsetMs", 0)) - seek_ms)

        try:
            audio_url = None
            token = None
            metadata = None

            if has_queued_tracks(store):
                tracks = store.get("currentTracks", [])
                idx = store.get("currentTrackIndex", 0)
                track = tracks[idx] if idx < len(tracks) else None
                if track:
                    qp = queue_parent_for_token_fallback(store)
                    audio_url = track.get("audioUrl")
                    token = track.get("id") or f"{qp}:{idx}"
                    metadata = {"title": track.get("title", ""),
                                "subtitle": store.get("feedbackContentTitle", "")}
            else:
                resolved = await _resolve_resume_playback(store)
                if not resolved:
                    return handler_input.response_builder \
                        .speak(NO_CONTENT_AVAILABLE) \
                        .response
                audio_url = resolved["audioUrl"]
                token = resolved["token"]
                metadata = resolved["metadata"]

            update_store(handler_input, {"lastOffsetMs": new_offset})
            tracks = store.get("currentTracks", [])
            idx = store.get("currentTrackIndex", 0)
            track = tracks[idx] if idx < len(tracks) else None
            play_url = _url_at_store_speed(store, audio_url,
                                           track.get("playback_speed") if track else None)

            return handler_input.response_builder \
                .speak(ssml(REWOUND(round(seek_ms / 1000)))) \
                .add_directive(build_play_directive({
                    "url": play_url, "token": token, "offsetMs": new_offset,
                    "metadata": metadata, "handlerInput": handler_input,
                })) \
                .response
        except Exception:
            return handler_input.response_builder \
                .speak(NO_CONTENT_AVAILABLE) \
                .response


class FastForwardIntentHandler(AbstractRequestHandler):
    """Fast-forwards the current track by a configurable step."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "FastForwardIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        gated = _gate_pending_feedback(handler_input)
        if gated:
            return gated

        store = get_store(handler_input)
        if not resolve_active_playback_token(store):
            return handler_input.response_builder \
                .speak(CANNOT_SEEK) \
                .response

        seek_ms = min(resolve_seek_ms(handler_input), settings.max_seek_ms)
        new_offset = (store.get("lastOffsetMs", 0)) + seek_ms

        try:
            audio_url = None
            token = None
            metadata = None

            if has_queued_tracks(store):
                tracks = store.get("currentTracks", [])
                idx = store.get("currentTrackIndex", 0)
                track = tracks[idx] if idx < len(tracks) else None
                if track:
                    qp = queue_parent_for_token_fallback(store)
                    audio_url = track.get("audioUrl")
                    token = track.get("id") or f"{qp}:{idx}"
                    metadata = {"title": track.get("title", ""),
                                "subtitle": store.get("feedbackContentTitle", "")}
            else:
                resolved = await _resolve_resume_playback(store)
                if not resolved:
                    return handler_input.response_builder \
                        .speak(NO_CONTENT_AVAILABLE) \
                        .response
                audio_url = resolved["audioUrl"]
                token = resolved["token"]
                metadata = resolved["metadata"]

            update_store(handler_input, {"lastOffsetMs": new_offset})
            tracks = store.get("currentTracks", [])
            idx = store.get("currentTrackIndex", 0)
            track = tracks[idx] if idx < len(tracks) else None
            play_url = _url_at_store_speed(store, audio_url,
                                           track.get("playback_speed") if track else None)

            return handler_input.response_builder \
                .speak(ssml(FAST_FORWARDED(round(seek_ms / 1000)))) \
                .add_directive(build_play_directive({
                    "url": play_url, "token": token, "offsetMs": new_offset,
                    "metadata": metadata, "handlerInput": handler_input,
                })) \
                .response
        except Exception:
            return handler_input.response_builder \
                .speak(NO_CONTENT_AVAILABLE) \
                .response
