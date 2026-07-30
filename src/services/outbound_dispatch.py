"""Dispatch Alexa-originated events through the configured outbound transport."""
from __future__ import annotations

import asyncio
import json
import time

import boto3
import httpx

from config import settings
from src.utils.webhook_signing import sign_payload


def dispatch(event_type: str, data: dict | None = None, options: dict | None = None):
    """Dispatch an event via SQS or HTTP based on configuration."""
    await_queue = bool((options or {}).get("awaitQueue"))
    envelope = {
        "event": event_type,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data": data or {},
    }
    if settings.SQS_OUT_QUEUE_URL:
        return _dispatch_via_sqs(settings.SQS_OUT_QUEUE_URL, envelope, await_queue)
    if settings.WEBHOOK_OUTBOUND_URL:
        return _dispatch_via_http(
            settings.WEBHOOK_OUTBOUND_URL,
            settings.WEBHOOK_OUTBOUND_SECRET or "",
            envelope,
            await_queue,
        )
    return None


def _dispatch_via_sqs(queue_url: str, envelope: dict, await_queue: bool):
    del await_queue
    try:
        region = settings.HEAR_DDB_REGION or settings.AWS_REGION or "eu-west-1"
        boto3.client("sqs", region_name=region).send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(envelope),
        )
    except Exception:
        pass
    return None


def _dispatch_via_http(url: str, secret: str, envelope: dict, await_queue: bool):
    del await_queue
    body = json.dumps(envelope)
    signature = sign_payload(body, secret)

    async def _send():
        async with httpx.AsyncClient() as client:
            try:
                await client.post(url, json=envelope, headers={
                    "Content-Type": "application/json",
                    "x-webhook-signature": signature["signature"],
                    "x-webhook-timestamp": signature["timestamp"],
                })
            except Exception:
                pass

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_send(), loop)
        else:
            asyncio.run(_send())
    except Exception:
        pass
    return None
