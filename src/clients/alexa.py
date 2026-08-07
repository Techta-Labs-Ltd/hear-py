from __future__ import annotations

from src.clients.pool import HttpPool
from src.services.store import get_store, update_store
from src.utils.playback_event_builder import normalize_playback_event
from src.utils.skill_request import get_user_id

_REMINDER_ALERT_TOKEN_KEY = "feedbackReminderAlertToken"
_STATUS_DISABLED = "disabled"

_ALEXA_POOL = HttpPool(timeout_ms=10_000)


class AlexaClient:
    __slots__ = ("_pool",)

    def __init__(self, pool: HttpPool | None = None) -> None:
        self._pool = pool or _ALEXA_POOL

    # ------------------------------------------- playback-event ingestion ----

    @staticmethod
    async def send_playback_events(
        *,
        alexa_user_id: str,
        events: list,
        handler_input=None,
    ) -> dict:
        resolved_user_id = str(alexa_user_id or "").strip()
        if not resolved_user_id and handler_input is not None:
            resolved_user_id = get_user_id(handler_input) or ""
        if not resolved_user_id or not isinstance(events, list) or not events:
            return {"status": None}
        accepted = 0
        for event in events:
            normalized = normalize_playback_event(event)
            if not normalized.get("contentId"):
                continue
            accepted += 1
        return {
            "status": _STATUS_DISABLED,
            "dispatched": 0,
            "failed": 0,
            "accepted": accepted,
        }

    # --------------------------------------------------- reminder management --

    @staticmethod
    def _get_service_client(handler_input) -> dict | None:
        try:
            sys = handler_input.request_envelope.context.System
            if not sys.apiEndpoint or not sys.apiAccessToken:
                return None
            return {
                "endpoint": str(sys.apiEndpoint).rstrip("/"),
                "token": sys.apiAccessToken,
            }
        except Exception:
            return None

    async def cancel_feedback_reminder(self, handler_input) -> None:
        service = AlexaClient._get_service_client(handler_input)
        store = get_store(handler_input)
        alert_token = store.get(_REMINDER_ALERT_TOKEN_KEY)
        if not alert_token:
            return
        if service:
            url = f"{service['endpoint']}/v1/alerts/reminders/{alert_token}"
            try:
                client = self._pool.get()
                await client.delete(
                    url,
                    headers={"Authorization": f"Bearer {service['token']}"},
                )
            except Exception:
                pass
        update_store(handler_input, {_REMINDER_ALERT_TOKEN_KEY: None})


# --- module-level singleton --------------------------------------------------

alexa = AlexaClient()

send_playback_events = alexa.send_playback_events
cancel_feedback_reminder = alexa.cancel_feedback_reminder
