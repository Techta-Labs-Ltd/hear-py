"""Dispatch Alexa-originated events through the configured outbound transport."""

from __future__ import annotations

import json
import logging
import time

import boto3
from config import settings

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
        logger.exception(
            "Hear outbound SQS dispatch failed event=%s", envelope["event"]
        )
        return False
