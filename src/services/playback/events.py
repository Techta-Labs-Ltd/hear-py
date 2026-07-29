from __future__ import annotations

from src.services.alexa.client import send_playback_events
from src.services.playback.session import read_playback_session
from src.services.storage.persistence import get_store
from src.utils.playback_event_builder import build_playback_event
from src.utils.skill_request import get_user_id

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
    await send_playback_events(
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
    return True


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


def consume_suppressed_playback_event(handler_input, kind: str) -> bool:
    del handler_input, kind
    return False
