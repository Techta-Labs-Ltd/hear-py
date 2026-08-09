from __future__ import annotations

import logging
import os
from typing import Any

from src.clients.pool import HttpPool
from src.utils.skill_request import get_request_type
from src.utils.speech import ssml

logger = logging.getLogger(__name__)


def _read(value: Any, *names: str) -> Any:
    for name in names:
        if isinstance(value, dict) and name in value:
            return value.get(name)
        if value is not None and hasattr(value, name):
            return getattr(value, name)
    return None


class ProgressiveResponseClient:
    """Best-effort client for Alexa's Send Directive service."""

    def __init__(
        self,
        pool: HttpPool | None = None,
        *,
        enabled: bool | None = None,
    ) -> None:
        self._pool = pool or HttpPool(timeout_ms=700)
        self._enabled = (
            enabled
            if enabled is not None
            else (os.environ.get("AWS_EXECUTION_ENV") or "").startswith("AWS_Lambda_")
        )

    async def send(self, handler_input, speech: str) -> bool:
        request_type = get_request_type(handler_input)
        if not self._enabled or request_type not in {"LaunchRequest", "IntentRequest"}:
            return False

        attributes = handler_input.attributes_manager.get_request_attributes()
        if attributes.get("_progressiveResponseSent"):
            return False

        envelope = handler_input.request_envelope
        request = _read(envelope, "request")
        context = _read(envelope, "context")
        system = _read(context, "System", "system")
        endpoint = str(_read(system, "apiEndpoint", "api_endpoint") or "").rstrip("/")
        token = str(_read(system, "apiAccessToken", "api_access_token") or "")
        request_id = str(_read(request, "requestId", "request_id") or "")
        if not endpoint or not token or not request_id:
            return False

        attributes["_progressiveResponseSent"] = True
        body = {
            "header": {"requestId": request_id},
            "directive": {
                "type": "VoicePlayer.Speak",
                "speech": ssml(speech),
            },
        }
        try:
            response = await self._pool.get().post(
                f"{endpoint}/v1/directives",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            delivered = response.status_code == 204
            if not delivered:
                logger.info(
                    "Hear: progressive response rejected status=%s requestId=%s",
                    response.status_code,
                    request_id,
                )
            return delivered
        except Exception as exc:
            logger.info(
                "Hear: progressive response unavailable requestId=%s error=%s",
                request_id,
                type(exc).__name__,
            )
            return False
