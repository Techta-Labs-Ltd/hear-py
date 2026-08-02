"""Dispatch Alexa-originated events through the configured outbound transport."""
from __future__ import annotations

import asyncio
import json
import logging
import time

import boto3
import httpx

from config import settings
from src.utils.webhook_signing import signed_webhook_headers

logger = logging.getLogger(__name__)


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
        response = boto3.client("sqs", region_name=region).send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(envelope),
        )
        return bool(response.get("MessageId"))
    except Exception:
        logger.exception("Hear outbound SQS dispatch failed event=%s", envelope["event"])
        return False


def _dispatch_via_http(url: str, secret: str, envelope: dict, await_queue: bool):
    del await_queue
    body = json.dumps(envelope)
    async def _send():
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url,
                    content=body,
                    headers=signed_webhook_headers(
                        body, secret, settings.api_key or "",
                    ),
                )
                response.raise_for_status()
            except Exception:
                logger.exception(
                    "Hear outbound HTTP dispatch failed event=%s",
                    envelope["event"],
                )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_send(), loop)
        else:
            asyncio.run(_send())
    except Exception:
        logger.exception("Hear outbound dispatch failed event=%s", envelope["event"])
        return False
    return True
