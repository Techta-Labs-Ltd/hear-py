from __future__ import annotations
from src.services.store import get_store
from src.utils.playback_event_builder import normalize_playback_event
from src.utils.skill_request import get_user_id
import httpx
from src.services.store import update_store
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

def _get_service_client(handler_input) -> dict | None:
    try:
        sys = handler_input.request_envelope.context.System
        if not sys.apiEndpoint or not sys.apiAccessToken:
            return None
        return {"endpoint": str(sys.apiEndpoint).rstrip("/"), "token": sys.apiAccessToken}
    except Exception:
        return None


async def cancel_feedback_reminder(handler_input) -> None:
    """Cancel the currently scheduled feedback reminder alert."""
    client = _get_service_client(handler_input)
    store = get_store(handler_input)
    alert_token = store.get("feedbackReminderAlertToken")
    if not alert_token:
        return
    if client:
        url = f"{client['endpoint']}/v1/alerts/reminders/{alert_token}"
        try:
            async with httpx.AsyncClient() as c:
                await c.delete(url, headers={"Authorization": f"Bearer {client['token']}"})
        except Exception:
            pass
    update_store(handler_input, {"feedbackReminderAlertToken": None})


