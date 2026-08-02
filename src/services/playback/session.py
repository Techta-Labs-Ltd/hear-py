from __future__ import annotations

import time
import uuid

from src.services.storage.persistence import get_store, update_store
from src.utils.skill_request import get_user_id

ACTIVE_STATUSES = {"starting", "playing", "paused"}
TERMINAL_STATUSES = {"completed", "abandoned", "failed"}


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


def clear_playback_session(handler_input):
    update_store(handler_input, {"activePlayback": None})


def has_unfinished_playback(store: dict) -> bool:
    state = read_playback_session(store)
    if not state or state.get("status") not in ACTIVE_STATUSES:
        return False
    audio_url = state.get("audioUrl") or store.get("currentAudioUrl")
    return isinstance(audio_url, str) and audio_url.strip().lower().startswith("https://")


async def resolve_playback_state(alexa_user_id: str | None, handler_input) -> dict:
    state = read_playback_session(get_store(handler_input)) if handler_input else None
    return {"source": "skill_persistence" if state else "none", "state": state}


async def save_playback_state(alexa_user_id: str | None, handler_input, fields: dict):
    if not handler_input:
        return None
    if alexa_user_id:
        fields = {**fields, "alexaUserId": alexa_user_id}
    return write_playback_session(handler_input, fields)


async def clear_all_playback_state(alexa_user_id: str | None, handler_input):
    if handler_input:
        clear_playback_session(handler_input)
