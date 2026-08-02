from __future__ import annotations

import asyncio
import json
import logging

import httpx

from config import settings
from src.utils.webhook_signing import sign_payload

logger = logging.getLogger(__name__)


async def _forward_to_backend(url: str, secret: str, envelope: dict):
    """Forward an event envelope to a backend HTTP endpoint with HMAC signing."""
    body = json.dumps(envelope)
    sig = sign_payload(body, secret)
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        resp = await client.post(url, content=body, headers={
            "Content-Type": "application/json",
            "x-webhook-signature": sig["signature"],
            "x-webhook-timestamp": sig["timestamp"],
        })
        resp.raise_for_status()
    return resp


def handler(event: dict, context=None):
    """AWS Lambda handler for consuming SQS outbound events and forwarding them via HTTP.

    Uses SQS partial-batch responses: only messages that fail to forward are
    returned in ``batchItemFailures`` so they alone are retried (and, after the
    queue's maxReceiveCount, land in the DLQ). Successful and unparseable
    messages are acknowledged (deleted) so a poison message can't loop forever.
    """
    url = settings.WEBHOOK_OUTBOUND_URL or ""
    secret = settings.WEBHOOK_OUTBOUND_SECRET or ""

    if not url:
        logger.error("Hear outbound webhook URL is not configured")
        return {
            "batchItemFailures": [
                {"itemIdentifier": record.get("messageId")}
                for record in (event.get("Records") or [])
                if record.get("messageId")
            ],
        }

    async def _run():
        records = event.get("Records") or []
        failures = []
        for record in records:
            try:
                envelope = json.loads(record.get("body") or "{}")
            except (json.JSONDecodeError, TypeError):
                continue  # unparseable — acknowledge (don't retry a poison message)
            try:
                response = await _forward_to_backend(url, secret, envelope)
                logger.info(
                    "Hear outbound webhook delivered event=%s messageId=%s status=%s",
                    envelope.get("event"),
                    record.get("messageId"),
                    response.status_code,
                )
            except Exception:
                logger.exception(
                    "Hear outbound webhook failed event=%s messageId=%s",
                    envelope.get("event"),
                    record.get("messageId"),
                )
                failures.append({"itemIdentifier": record.get("messageId")})
        return {"batchItemFailures": failures}

    return asyncio.run(_run())
