"""Core audio-playback primitives.

Historically these lived in ``src.handlers.intents.launch``, which meant every
module that needed to start playback had to import a *handler* module — and
because that handler imports large parts of the app, callers were forced into
deferred (in-function) imports to dodge import cycles.

They are relocated here, a low-level module that depends only on services and
utils, so that handlers and utils can import them at the top of the file
without creating a cycle.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ask_sdk_core.handler_input import HandlerInput

from config import settings
from src.services.persistence import get_store, update_store, add_to_history, clear_queue
from src.services.alexa_reminders import cancel_feedback_reminder
from src.utils.audio import (
    build_play_directive, build_content_metadata, resolve_track_audio,
    resolve_audio_url_for_speed, resolve_effective_playback_speed,
)
from src.utils.listen_tracker import finalize_previous_track_if_any
from src.utils.normalize_content_item import content_title_for_speech, pick_content_credit
from src.utils.speech import (
    ssml, humanize_spoken_title, get_mid_playback_prompt, NO_CONTENT_AVAILABLE,
)

logger = logging.getLogger(__name__)


def extract_playback_speeds(content: Dict[str, Any], track_index: int = 0):
    if not content:
        return None
    tracks = content.get("tracks")
    if isinstance(tracks, list) and tracks:
        track = tracks[track_index] if track_index < len(tracks) else tracks[0]
        speeds = track.get("playback_speed") if track else None
        if isinstance(speeds, list) and speeds:
            return speeds
    speeds = content.get("playback_speed")
    if isinstance(speeds, list) and speeds:
        return speeds
    return None


def prepare_playback_audio_and_store(
    handler_input: HandlerInput, content: Dict[str, Any], track_index: int = 0
) -> Optional[Dict[str, Any]]:
    """Resolve audio URL and persist playback metadata for the given content item."""
    track_info = resolve_track_audio(content, track_index)
    if not track_info.get("audioUrl"):
        return None

    store = get_store(handler_input)
    finalize_previous_track_if_any(handler_input, {"offsetMs": store.get("lastOffsetMs", 0)})

    current_speeds = extract_playback_speeds(content, track_index)
    effective_speed = resolve_effective_playback_speed(
        store.get("playbackSpeed", settings.default_speed), current_speeds,
    )
    play_count = store.get("playCount", 0) + 1
    track_duration = track_info.get("durationSecs") or content.get("durationSecs")
    prompt_text = get_mid_playback_prompt(
        track_info.get("effectiveCategory") or content.get("category"),
        play_count, track_duration,
    )
    queue_parent = track_info.get("playbackParentId") if track_info.get("isMultiTrack") else None
    title_for_store = content_title_for_speech(content)
    credit_for_store = pick_content_credit(content)

    update_store(handler_input, {
        "feedbackContentId": track_info.get("trackId") or content.get("id"),
        "playbackTrackId": track_info.get("trackId"),
        "lastToken": track_info.get("token"),
        "lastOffsetMs": 0,
        "feedbackCategory": track_info.get("effectiveCategory"),
        "feedbackCreator": credit_for_store,
        "feedbackCreatorId": content.get("creatorId") if credit_for_store else None,
        "feedbackContentTitle": title_for_store,
        "feedbackPromptText": prompt_text,
        "currentContentId": content.get("id"),
        "lastPlayedCatalogId": content.get("id"),
        "currentContentTitle": title_for_store,
        "currentCreator": credit_for_store,
        "currentCreatorId": content.get("creatorId") if credit_for_store else None,
        "currentCategory": track_info.get("effectiveCategory"),
        "currentSummary": content.get("summary"),
        "playCount": play_count,
        "playbackParentId": track_info.get("playbackParentId"),
        "playbackContentType": track_info.get("contentType"),
        "currentPublicationId": queue_parent,
        "currentTrackIndex": track_info.get("trackIndex"),
        "currentTotalTracks": track_info.get("totalTracks") if track_info.get("isMultiTrack") else 0,
        "currentTracks": content.get("tracks", []) if track_info.get("isMultiTrack") else [],
        "awaitingContinueAfterFlag": False,
        "showHomeBrowseOnNextLaunch": False,
        "playbackDurationEstimateMs": None,
        "currentPlaybackSpeeds": current_speeds,
        "playbackSpeed": store.get("playbackSpeed", settings.default_speed),
        "currentDurationSecs": track_duration,
    })

    add_to_history(handler_input, content)
    audio_url = resolve_audio_url_for_speed(track_info["audioUrl"], effective_speed, current_speeds)

    return {"trackInfo": track_info, "audioUrl": audio_url}


async def start_playback(
    handler_input: HandlerInput, content: Dict[str, Any], intro_text: str,
    track_index: int = 0, options: Optional[Dict[str, Any]] = None,
):
    """Build and return an Alexa response that starts audio playback."""
    cancel_feedback_reminder(handler_input)

    if not (options or {}).get("preserveSessionQueue"):
        clear_queue(handler_input)

    prepared = prepare_playback_audio_and_store(handler_input, content, track_index)
    if not prepared:
        return handler_input.response_builder \
            .speak(ssml(NO_CONTENT_AVAILABLE)) \
            .response

    track_info = prepared["trackInfo"]
    audio_url = prepared["audioUrl"]
    if not track_info.get("token"):
        logger.error("Hear: start_playback missing token contentId=%s", content.get("id"))
        return handler_input.response_builder \
            .speak(ssml(NO_CONTENT_AVAILABLE)) \
            .response

    store = get_store(handler_input)
    speed = store.get("playbackSpeed", settings.default_speed)

    full_intro = intro_text
    if track_info.get("isMultiTrack"):
        pos = f"{track_info['trackIndex'] + 1} of {track_info['totalTracks']}"
        raw_track_title = track_info.get("trackTitle")
        safe_track_title = humanize_spoken_title(raw_track_title) if raw_track_title else None
        safe_collection = humanize_spoken_title(track_info.get("collectionTitle"))
        spoken_parent = humanize_spoken_title(content_title_for_speech(content))

        if safe_collection and safe_collection != spoken_parent:
            if safe_track_title:
                full_intro += f" From {safe_collection}: track {pos}, {safe_track_title}."
            else:
                full_intro += f" From {safe_collection}: track {pos}."
        elif safe_track_title:
            full_intro += f" Track {pos}: {safe_track_title}."
        else:
            full_intro += f" Track {pos}."

    spoken_intro = ssml(full_intro)
    duration_secs = store.get("currentDurationSecs")

    return handler_input.response_builder \
        .speak(spoken_intro) \
        .add_directive(build_play_directive({
            "url": audio_url,
            "token": track_info["token"],
            "metadata": build_content_metadata(
                content, track_info.get("trackTitle"), track_info.get("effectiveCategory"),
            ),
            "progressReport": True,
            "durationSecs": duration_secs,
            "handlerInput": handler_input,
        })) \
        .response
