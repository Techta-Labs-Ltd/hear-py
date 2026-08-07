from __future__ import annotations
import time
import uuid
from src.services.store import get_store, update_store
from src.utils.skill_request import get_user_id
import logging
from typing import Any
from ask_sdk_core.handler_input import HandlerInput
from config import settings
from src.clients.alexa import cancel_feedback_reminder
from src.services.queue import read_playback_queue
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
from src.clients.alexa import send_playback_events
from src.utils.playback_event_builder import build_playback_event
from src.clients.hear import search
from src.services.queue import cached_queue_content, move_queue
from src.utils.speech import LOCAL_CONTENT_FALLBACK
from src.services.persistence import _normalize_play_history_entry

ACTIVE_STATUSES = {"starting", "playing", "paused"}


def read_playback_session(store: dict) -> dict | None:
    """Return the canonical active playback record."""
    state = store.get("activePlayback") if isinstance(store, dict) else None
    if not isinstance(state, dict) or not state.get("contentId"):
        return None
    return dict(state)


def write_playback_session(handler_input, fields: dict) -> dict | None:
    """Merge fields into canonical active playback state."""
    if not isinstance(fields, dict):
        return None
    current = read_playback_session(get_store(handler_input)) or {}
    merged = {**current, **fields, "updatedAt": int(time.time() * 1000)}
    if not merged.get("contentId"):
        return None
    merged["token"] = merged["contentId"]
    update_store(handler_input, {"activePlayback": merged})
    return merged


def create_playback_session(
    handler_input,
    content: dict,
    *,
    queue_id: str | None = None,
    queue_index: int = 0,
    offset_ms: int = 0,
) -> dict:
    """Create a starting playback record from one flat playable content item."""
    now = int(time.time() * 1000)
    state = {
        "alexaUserId": get_user_id(handler_input),
        "contentId": content["contentId"],
        "token": content["contentId"],
        "title": content.get("spokenTitle") or content.get("displayTitle") or content.get("title"),
        "creatorId": content.get("creatorId"),
        "creatorName": content.get("creatorName") or content.get("creator"),
        "organizationId": content.get("organizationId"),
        "organizationName": content.get("organizationName"),
        "publicationId": content.get("publicationId"),
        "publicationTitle": content.get("publicationTitle"),
        "isPublication": bool(content.get("isPublication")),
        "trackIndex": content.get("trackIndex"),
        "trackCount": content.get("trackCount"),
        "category": content.get("category"),
        "queueId": queue_id,
        "queueIndex": max(0, int(queue_index or 0)),
        "audioUrl": content.get("audioUrl"),
        "durationMs": content.get("durationMs"),
        "offsetMs": max(0, int(offset_ms or 0)),
        "listenedMs": 0,
        "sessionId": f"{content['contentId']}:{uuid.uuid4().hex}",
        "status": "starting",
        "startedAt": now,
        "updatedAt": now,
    }
    update_store(handler_input, {"activePlayback": state})
    return state


def has_unfinished_playback(store: dict) -> bool:
    state = read_playback_session(store)
    if not state or state.get("status") not in ACTIVE_STATUSES:
        return False
    audio_url = state.get("audioUrl") or store.get("currentAudioUrl")
    return isinstance(audio_url, str) and audio_url.strip().lower().startswith("https://")


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

USER_PLAYBACK_EVENT_TYPES = {
    "USER_STOPPED": "user_stopped",
    "PAUSED": "paused",
    "RESUMED": "resumed",
    "CANCELLED": "cancelled",
}


async def emit_listening_event(handler_input, event_type: str, state: dict | None = None) -> bool:
    active = state or read_playback_session(get_store(handler_input))
    user_id = get_user_id(handler_input)
    if not user_id or not active or not active.get("contentId") or not active.get("sessionId"):
        return False
    result = await send_playback_events(
        alexa_user_id=user_id,
        handler_input=handler_input,
        events=[build_playback_event(
            content_id=active["contentId"],
            session_id=active["sessionId"],
            event_type=event_type,
            position_ms=active.get("offsetMs") or 0,
            duration_ms=active.get("durationMs") or 0,
            listened_ms=active.get("listenedMs") or 0,
            creator_id=active.get("creatorId"),
            publication_id=active.get("publicationId"),
            queue_id=active.get("queueId"),
        )],
    )
    return result.get("status") == "dispatched"


async def emit_user_playback_event(
    handler_input,
    options: dict | None = None,
    *,
    event_type=None,
    event_label=None,
    **_,
) -> bool:
    options = options or {}
    return await emit_listening_event(
        handler_input,
        event_label
        or event_type
        or options.get("eventLabel")
        or options.get("eventType")
        or "event",
    )


class PlaybackService:
    async def flush_previous(
        self,
        alexa_user_id: str,
        override_offset_ms: int | None = None,
        handler_input=None,
    ) -> dict | None:
        """Persist an unfinished item as paused; never create duplicate state."""
        del alexa_user_id
        if handler_input is None:
            return None
        state = read_playback_session(get_store(handler_input))
        if not state or state.get("status") not in {"starting", "playing", "paused"}:
            return None
        patch = {"status": "paused"}
        if override_offset_ms is not None:
            patch["offsetMs"] = max(0, int(override_offset_ms))
        state = write_playback_session(handler_input, patch)
        await emit_listening_event(handler_input, "paused", state)
        return state


playback_service = PlaybackService()


async def flush_previous_track(
    alexa_user_id: str,
    override_offset_ms: int | None = None,
    handler_input=None,
) -> dict | None:
    return await playback_service.flush_previous(
        alexa_user_id,
        override_offset_ms,
        handler_input,
    )

def add_to_history(handler_input, content_or_id, recording_id: str | None = None) -> dict:
    """Insert an entry at the front of the play history, deduping and capping.

    Accepts a full content dict (to store a playable snapshot) or a plain
    content-id string/dict for backward compatibility.
    """
    store = get_store(handler_input)
    history = [_normalize_play_history_entry(e) for e in (store.get("playHistory") or [])]
    history = [h for h in history if h is not None]
    if isinstance(content_or_id, dict) and content_or_id.get("audioUrl"):
        entry = _normalize_play_history_entry(content_or_id)
        if not entry:
            return store
        cid = entry["id"]
    else:
        cid = str(content_or_id) if content_or_id is not None else None
        entry = {"id": cid} if cid else None
    if not cid:
        return store
    for i, h in enumerate(history):
        if h["id"] == cid:
            history.pop(i)
            break
    history.insert(0, entry)
    cap = settings.max_history
    return update_store(handler_input, {"playHistory": history[:cap]})

async def _resolve_content(handler_input, content_id: str) -> dict | None:
    cached = cached_queue_content(get_store(handler_input), content_id)
    if cached:
        return cached
    result = await search({
        "query": "",
        "filter": {"contentIds": [content_id]},
        "page": 0,
        "limit": 1,
        "alexaUserId": get_user_id(handler_input),
    })
    return result["results"][0] if result.get("results") else None


async def play_next_queued_item(
    handler_input,
    *,
    speak_intro: bool = True,
    intro_prefix: str | None = None,
):
    """Advance the canonical queue and resolve its next content through search."""
    content_id = move_queue(handler_input, 1)
    if not content_id:
        return None
    content = await _resolve_content(handler_input, content_id)
    if not content:
        return None
    title = content_title_for_speech(content)
    credit = pick_content_credit(content)
    intro = LOCAL_CONTENT_FALLBACK(title, credit) if speak_intro else ""
    if intro_prefix:
        intro = f"{intro_prefix} {intro}".strip()
    return await start_playback(handler_input, content, intro)
