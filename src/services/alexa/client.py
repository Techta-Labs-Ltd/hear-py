from __future__ import annotations

from src.services.storage.persistence import get_store
from src.utils.playback_event_builder import normalize_playback_event
from src.webhooks.dispatch import dispatch


async def send_playback_events(
    *,
    alexa_user_id: str,
    events: list,
    handler_input=None,
) -> dict:
    """Dispatch canonical content listening events to the outbound pipeline."""
    if not alexa_user_id or not isinstance(events, list) or not events:
        return {"status": None}
    listener_id = None
    if handler_input is not None:
        listener_id = get_store(handler_input).get("listenerId")
    for event in events:
        normalized = normalize_playback_event(event)
        content_id = normalized.get("contentId")
        if not content_id:
            continue
        payload = {
            **normalized,
            "alexaUserId": alexa_user_id,
            "listenerId": listener_id,
        }
        dispatch(
            f"playback.{str(normalized.get('eventType') or 'event').lower()}",
            payload,
        )
    return {"status": "dispatched"}
