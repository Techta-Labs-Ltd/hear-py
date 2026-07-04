from __future__ import annotations

import asyncio
import concurrent.futures
import json

import httpx

from config import settings
from src.webhooks.signing import sign_payload


async def _forward_to_backend(url: str, secret: str, envelope: dict):
    """Forward an event envelope to a backend HTTP endpoint with HMAC signing."""
    body = json.dumps(envelope)
    sig = sign_payload(body, secret)
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        resp = await client.post(url, json=envelope, headers={
            "Content-Type": "application/json",
            "x-webhook-signature": sig["signature"],
            "x-webhook-timestamp": sig["timestamp"],
        })
        resp.raise_for_status()
    return resp


def handler(event: dict, context=None):
    """AWS Lambda handler for consuming SQS outbound events and forwarding them via HTTP."""
    url = settings.WEBHOOK_OUTBOUND_URL or ""
    secret = settings.WEBHOOK_OUTBOUND_SECRET or ""

    if not url:
        return

    async def _run():
        records = event.get("Records") or []
        errors = []
        for record in records:
            try:
                envelope = json.loads(record.get("body") or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            try:
                await _forward_to_backend(url, secret, envelope)
            except Exception as e:
                errors.append({"event": envelope.get("event"), "status": getattr(getattr(e, "response", None), "status_code", None)})
        if errors:
            raise Exception(f"Outbound consumer partial failure: {len(errors)} of {len(records)} messages failed")

    loop = asyncio.get_event_loop()
    if loop.is_running():
        future = asyncio.run_coroutine_threadsafe(_run(), loop)
        return future.result()
    else:
        return asyncio.run(_run())
