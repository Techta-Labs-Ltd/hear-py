from __future__ import annotations

import logging

from config import settings
from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.ssml import Ssml
from src.clients.pool import HttpPool


class ProgressiveResponseSupport:
    logger = logging.getLogger(__name__)


class ProgressiveResponseClient:
    """Best-effort client for Alexa's Send Directive service."""

    def __init__(self, pool: HttpPool | None = None, *, enabled: bool | None = None) -> None:
        self._pool = pool or HttpPool(timeout_ms=settings.HEAR_PROGRESSIVE_TIMEOUT_MS)
        self._enabled = enabled if enabled is not None else settings.progressive_responses_enabled

    async def send(self, handler_input, speech: str) -> bool:
        request_type = AlexaRequest.get_request_type(handler_input)
        if not self._enabled or request_type not in {"LaunchRequest", "IntentRequest"}:
            return False
        attributes = RequestContext.request(handler_input)
        if attributes.get("_progressiveResponseSent"):
            return False
        envelope = handler_input.request_envelope
        request = AlexaRequest.read(envelope, "request")
        context = AlexaRequest.read(envelope, "context")
        system = AlexaRequest.read(context, "System", "system")
        endpoint = str(AlexaRequest.read(system, "apiEndpoint", "api_endpoint") or "").rstrip("/")
        token = str(AlexaRequest.read(system, "apiAccessToken", "api_access_token") or "")
        request_id = str(AlexaRequest.read(request, "requestId", "request_id") or "")
        if not endpoint or not token or (not request_id):
            return False
        attributes["_progressiveResponseSent"] = True
        body = {
            "header": {"requestId": request_id},
            "directive": {"type": "VoicePlayer.Speak", "speech": Ssml.ssml(speech)},
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
                ProgressiveResponseSupport.logger.info(
                    "Hear: progressive response rejected status=%s requestId=%s",
                    response.status_code,
                    request_id,
                )
            return delivered
        except Exception as exc:
            ProgressiveResponseSupport.logger.info(
                "Hear: progressive response unavailable requestId=%s error=%s",
                request_id,
                type(exc).__name__,
            )
            return False
