from __future__ import annotations

from config import settings
from src.clients.pool import HttpPool


class AlexaClient:
    __slots__ = ("_pool",)

    def __init__(self, pool: HttpPool | None = None) -> None:
        self._pool = pool or HttpPool(timeout_ms=settings.HEAR_ALEXA_API_TIMEOUT_MS)

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

    async def cancel_feedback_reminder(self, handler_input, alert_token: str) -> None:
        service = AlexaClient._get_service_client(handler_input)
        if not alert_token:
            return
        if service:
            url = f"{service['endpoint']}/v1/alerts/reminders/{alert_token}"
            try:
                client = self._pool.get()
                await client.delete(url, headers={"Authorization": f"Bearer {service['token']}"})
            except Exception:
                pass
