"""Start playback for one canonical flat content item."""
from __future__ import annotations

import logging
from typing import Any

from ask_sdk_core.handler_input import HandlerInput

from config import settings
from src.services.alexa.reminders import cancel_feedback_reminder
from src.services.playback.session import (
    create_playback_session,
    write_playback_session,
)
from src.services.queue.state import read_playback_queue
from src.services.storage.persistence import add_to_history, get_store, update_store
from src.utils.audio import (
    build_content_metadata,
    build_play_directive,
    resolve_audio_url_for_speed,
    resolve_effective_playback_speed,
)
from src.utils.normalize_content_item import (
    content_title_for_speech,
    is_playable_content_item,
    pick_content_credit,
)
from src.utils.speech import NO_CONTENT_AVAILABLE, WELCOME_REPROMPT, ssml

logger = logging.getLogger(__name__)


def _play_response(handler_input: HandlerInput, intro_text: str, directive: dict) -> dict:
    """Hand AudioPlayer control to Alexa and close the foreground session."""
    return (
        handler_input.response_builder
        .speak(ssml(intro_text))
        .add_directive(directive)
        .set_should_end_session(True)
        .response
    )


async def prepare_playback_audio_and_store(
    handler_input: HandlerInput,
    content: dict[str, Any],
    offset_ms: int = 0,
) -> dict | None:
    """Validate content and create canonical starting playback state."""
    if not is_playable_content_item(content):
        return None
    store = get_store(handler_input)
    speeds = content.get("playbackSpeeds") or []
    effective_speed = resolve_effective_playback_speed(
        store.get("playbackSpeed", settings.default_speed),
        speeds,
    )
    queue = read_playback_queue(store)
    queue_id = queue.get("queueId") if queue else None
    queue_index = queue.get("currentIndex", 0) if queue else 0
    state = create_playback_session(
        handler_input,
        content,
        queue_id=queue_id,
        queue_index=queue_index,
        offset_ms=offset_ms,
    )
    title = content_title_for_speech(content)
    creator = pick_content_credit(content)
    update_store(handler_input, {
        "playCount": store.get("playCount", 0) + 1,
        "lastToken": content["contentId"],
        "lastOffsetMs": max(0, int(offset_ms or 0)),
        "currentContentId": content["contentId"],
        "currentContentTitle": title,
        "currentCreator": creator,
        "currentCreatorId": content.get("creatorId"),
        "currentOrganization": content.get("organizationName"),
        "currentOrganizationId": content.get("organizationId"),
        "currentPublicationId": content.get("publicationId"),
        "currentTrackIndex": content.get("trackIndex"),
        "currentTotalTracks": content.get("trackCount"),
        "currentCategory": content.get("category"),
        "currentDurationSecs": (
            content["durationMs"] / 1000
            if isinstance(content.get("durationMs"), (int, float))
            else None
        ),
        "currentPlaybackSpeeds": speeds,
        "currentAudioUrl": content["audioUrl"],
    })
    add_to_history(handler_input, content)
    audio_url = resolve_audio_url_for_speed(
        content["audioUrl"],
        effective_speed,
        speeds,
    )
    return {"state": state, "audioUrl": audio_url}


async def start_playback(
    handler_input: HandlerInput,
    content: dict[str, Any],
    intro_text: str,
    track_index: int = 0,
    options: dict[str, Any] | None = None,
):
    """Return a play response using contentId as the stable Alexa token."""
    del track_index
    await cancel_feedback_reminder(handler_input)
    offset_ms = int((options or {}).get("offsetMs") or 0)
    prepared = await prepare_playback_audio_and_store(
        handler_input,
        content,
        offset_ms,
    )
    if not prepared:
        return (
            handler_input.response_builder
            .speak(ssml(NO_CONTENT_AVAILABLE))
            .reprompt(ssml(WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )
    state = prepared["state"]
    directive = build_play_directive(
        url=prepared["audioUrl"],
        token=state["contentId"],
        offset_ms=state["offsetMs"],
        metadata=build_content_metadata(content),
        progress_report=True,
        duration_secs=(
            state["durationMs"] / 1000
            if isinstance(state.get("durationMs"), (int, float))
            else None
        ),
        handler_input=handler_input,
    )
    if not directive:
        logger.error("Hear: could not build play directive contentId=%s", state["contentId"])
        return (
            handler_input.response_builder
            .speak(ssml(NO_CONTENT_AVAILABLE))
            .reprompt(ssml(WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )
    return _play_response(handler_input, intro_text, directive)


async def resume_playback(
    handler_input: HandlerInput,
    state: dict[str, Any],
    intro_text: str,
):
    """Resume directly from canonical persisted playback state.

    Resume must not depend on a catalog lookup: the backend may no longer
    return the item, and the active record already owns the stable token,
    playable URL, metadata, and exact offset.
    """
    content_id = str(state.get("contentId") or "").strip()
    audio_url = str(
        state.get("audioUrl") or get_store(handler_input).get("currentAudioUrl") or ""
    ).strip()
    content = {
        "contentId": content_id,
        "title": state.get("title"),
        "spokenTitle": state.get("title"),
        "audioUrl": audio_url,
        "creatorId": state.get("creatorId"),
        "creatorName": state.get("creatorName"),
        "publicationId": state.get("publicationId"),
        "publicationTitle": state.get("publicationTitle"),
        "durationMs": state.get("durationMs"),
        "playbackSpeeds": get_store(handler_input).get("currentPlaybackSpeeds") or [],
    }
    if not is_playable_content_item(content):
        return (
            handler_input.response_builder
            .speak(ssml(NO_CONTENT_AVAILABLE))
            .reprompt(ssml(WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    offset_ms = max(0, int(state.get("offsetMs") or 0))
    speeds = content["playbackSpeeds"]
    effective_speed = resolve_effective_playback_speed(
        get_store(handler_input).get("playbackSpeed", settings.default_speed),
        speeds,
    )
    resolved_url = resolve_audio_url_for_speed(audio_url, effective_speed, speeds)
    resumed = write_playback_session(handler_input, {
        "status": "starting",
        "offsetMs": offset_ms,
    })
    update_store(handler_input, {
        "lastToken": content_id,
        "lastOffsetMs": offset_ms,
        "currentContentId": content_id,
        "currentContentTitle": state.get("title"),
        "currentAudioUrl": audio_url,
    })
    directive = build_play_directive(
        url=resolved_url,
        token=content_id,
        offset_ms=offset_ms,
        metadata=build_content_metadata(content),
        progress_report=True,
        duration_secs=(
            resumed["durationMs"] / 1000
            if resumed and isinstance(resumed.get("durationMs"), (int, float))
            else None
        ),
        handler_input=handler_input,
    )
    if not directive:
        write_playback_session(handler_input, {"status": "failed"})
        return (
            handler_input.response_builder
            .speak(ssml(NO_CONTENT_AVAILABLE))
            .reprompt(ssml(WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )
    return _play_response(handler_input, intro_text, directive)
