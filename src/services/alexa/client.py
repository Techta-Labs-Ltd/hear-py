from __future__ import annotations
from src.services.storage.persistence import get_store
from src.utils.playback_event_builder import normalize_playback_event
from src.utils.skill_request import get_user_id


async def send_playback_events(
    *,
    alexa_user_id: str,
    events: list,
    handler_input=None,
) -> dict:
    """Accept canonical listening events without external delivery."""
    resolved_user_id = str(alexa_user_id or "").strip()
    if not resolved_user_id and handler_input is not None:
        resolved_user_id = get_user_id(handler_input) or ""
    if not resolved_user_id or not isinstance(events, list) or not events:
        return {"status": None}
    listener_id = None
    if handler_input is not None:
        listener_id = get_store(handler_input).get("listenerId")
    accepted = 0
    for event in events:
        normalized = normalize_playback_event(event)
        content_id = normalized.get("contentId")
        if not content_id:
            continue
        accepted += 1
    return {
        "status": "disabled",
        "dispatched": 0,
        "failed": 0,
        "accepted": accepted,
    }
