from __future__ import annotations

import asyncio
import json
import logging

import httpx

from config import settings
from src.utils.webhook_signing import signed_webhook_headers

logger = logging.getLogger(__name__)


async def _forward_to_backend(
    client: httpx.AsyncClient,
    url: str,
    secret: str,
    envelope: dict,
) -> httpx.Response:
    """Forward one event through a caller-owned pooled HTTP client."""
    body = json.dumps(envelope)
    response = await client.post(
        url,
        content=body,
        headers=signed_webhook_headers(body, secret, settings.api_key or ""),
    )
    response.raise_for_status()
    return response


def handler(event: dict, context=None) -> dict:
    """Forward an SQS batch and report only retryable record failures."""
    del context
    url = settings.WEBHOOK_OUTBOUND_URL or ""
    secret = settings.WEBHOOK_OUTBOUND_SECRET or ""
    records = event.get("Records") or []
    if not url:
        logger.error("Hear outbound webhook URL is not configured")
        return {
            "batchItemFailures": [
                {"itemIdentifier": record.get("messageId")}
                for record in records if record.get("messageId")
            ],
        }

    async def run() -> dict:
        failures = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            for record in records:
                try:
                    envelope = json.loads(record.get("body") or "{}")
                except (json.JSONDecodeError, TypeError):
                    continue
                try:
                    response = await _forward_to_backend(
                        client, url, secret, envelope,
                    )
                    logger.info(
                        "Hear outbound webhook delivered event=%s messageId=%s status=%s",
                        envelope.get("event"), record.get("messageId"),
                        response.status_code,
                    )
                except Exception:
                    logger.exception(
                        "Hear outbound webhook failed event=%s messageId=%s",
                        envelope.get("event"), record.get("messageId"),
                    )
                    failures.append({"itemIdentifier": record.get("messageId")})
        return {"batchItemFailures": failures}

    return asyncio.run(run())
