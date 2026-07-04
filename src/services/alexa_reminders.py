from __future__ import annotations
import datetime
import httpx
from config import settings, permission_scopes
from src.services.store_core import get_store, update_store
from src.utils.speech import escape_ssml_lite, FEEDBACK_REMINDER_SPOKEN


def has_reminder_permission(handler_input) -> bool:
    """Check whether the Alexa request grants the reminders read/write scope."""
    try:
        scopes = handler_input.request_envelope.context.System.user.permissions.scopes
        return (scopes or {}).get(permission_scopes.REMINDERS_READWRITE, {}).get("status") == "GRANTED"
    except Exception:
        return False


def _get_service_client(handler_input) -> dict | None:
    try:
        sys = handler_input.request_envelope.context.System
        if not sys.api_endpoint or not sys.api_access_token:
            return None
        return {"endpoint": str(sys.api_endpoint).rstrip("/"), "token": sys.api_access_token}
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


def _build_reminder_payload(handler_input, offset_seconds: int) -> dict:
    try:
        locale = handler_input.request_envelope.request.locale or "en-GB"
    except Exception:
        locale = "en-GB"
    text = FEEDBACK_REMINDER_SPOKEN
    safe = escape_ssml_lite(text)
    return {
        "requestTime": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "trigger": {
            "type": "SCHEDULED_RELATIVE",
            "offsetInSeconds": str(min(86400, max(60, offset_seconds))),
        },
        "alertInfo": {
            "spokenInfo": {
                "content": [{"locale": locale, "text": text, "ssml": f"<speak>{safe}</speak>"}],
            },
        },
        "pushNotification": {"status": "ENABLED"},
    }


async def schedule_feedback_reminder_if_needed(handler_input, *, remaining_ms: int) -> None:
    """Schedule an Alexa reminder to prompt the user for feedback after playback ends."""
    if not settings.HEAR_FEEDBACK_REMINDER:
        return
    if not has_reminder_permission(handler_input):
        return
    client = _get_service_client(handler_input)
    if not client:
        return
    await cancel_feedback_reminder(handler_input)
    offset_seconds = -(-max(0, remaining_ms) // 1000) + settings.HEAR_FEEDBACK_REMINDER_OFFSET_SEC
    body = _build_reminder_payload(handler_input, offset_seconds)
    try:
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{client['endpoint']}/v1/alerts/reminders",
                json=body,
                headers={
                    "Authorization": f"Bearer {client['token']}",
                    "Content-Type": "application/json",
                },
            )
            data = resp.json()
            alert_token = data.get("alertToken")
            if alert_token:
                update_store(handler_input, {"feedbackReminderAlertToken": alert_token})
    except Exception:
        pass
