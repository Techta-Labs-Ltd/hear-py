from __future__ import annotations

import asyncio
import concurrent.futures
import json
import time

import boto3
import httpx

from config import settings
from src.webhooks.signing import sign_payload


def dispatch(event_type: str, data: dict | None = None, options: dict | None = None):
    """Dispatch an event via SQS or HTTP webhook based on configuration."""
    opts = options or {}
    await_queue = bool(opts.get("awaitQueue"))
    envelope = {"event": event_type, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "data": data or {}}

    sqs_url = settings.SQS_OUT_QUEUE_URL or ""
    http_url = settings.WEBHOOK_OUTBOUND_URL or ""
    secret = settings.WEBHOOK_OUTBOUND_SECRET or ""

    if sqs_url:
        return _dispatch_via_sqs(sqs_url, envelope, await_queue)
    if http_url:
        return _dispatch_via_http(http_url, secret, envelope, await_queue)
    return None


def _dispatch_via_sqs(queue_url: str, envelope: dict, await_queue: bool):
    """Send an event envelope to an SQS queue."""
    try:
        region = settings.HEAR_DDB_REGION or settings.AWS_REGION or "eu-west-1"
        client = boto3.client("sqs", region_name=region)
        body = json.dumps(envelope)
        client.send_message(QueueUrl=queue_url, MessageBody=body)
        return None
    except Exception:
        pass
    return None


def _dispatch_via_http(url: str, secret: str, envelope: dict, await_queue: bool):
    """Send an event envelope to an HTTP webhook endpoint."""
    body = json.dumps(envelope)
    sig = sign_payload(body, secret)

    async def _send():
        async with httpx.AsyncClient() as client:
            try:
                await client.post(url, json=envelope, headers={
                    "Content-Type": "application/json",
                    "x-webhook-signature": sig["signature"],
                    "x-webhook-timestamp": sig["timestamp"],
                })
            except Exception:
                pass

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            future = asyncio.run_coroutine_threadsafe(_send(), loop)
        else:
            asyncio.run(_send())
    except Exception:
        pass
    return None
