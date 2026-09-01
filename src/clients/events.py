from __future__ import annotations

import json
import logging

import boto3

from config import settings
from src.clients.pool import HttpCircuitOpen, HttpPool
from src.utils.events import EventUtils


class SqsEventClient:
    logger = logging.getLogger(__name__)
    __slots__ = ("_queue_url", "_region", "_client")

    def __init__(
        self,
        *,
        queue_url: str | None = None,
        region: str | None = None,
        client=None,
    ) -> None:
        self._queue_url = (settings.SQS_OUT_QUEUE_URL if queue_url is None else queue_url).strip()
        self._region = region or settings.ddb_region
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self._queue_url)

    def send(self, envelope: dict) -> bool:
        if not self.enabled:
            return False
        try:
            if self._client is None:
                self._client = boto3.client("sqs", region_name=self._region)
            message = {
                "QueueUrl": self._queue_url,
                "MessageBody": json.dumps(envelope, separators=(",", ":")),
                "MessageAttributes": EventUtils.sqs_message_attributes(envelope),
            }
            response = self._client.send_message(**message)
            return bool(response.get("MessageId"))
        except Exception:
            self.logger.exception(
                "Hear outbound SQS dispatch failed event=%s", envelope.get("event")
            )
            return False


class WebhookEventClient:
    logger = logging.getLogger(__name__)
    __slots__ = ("_url", "_secret", "_api_key", "_pool")

    def __init__(
        self,
        *,
        url: str | None = None,
        secret: str | None = None,
        api_key: str | None = None,
        pool: HttpPool | None = None,
    ) -> None:
        self._url = (settings.WEBHOOK_OUTBOUND_URL if url is None else url).strip()
        configured_secret = settings.WEBHOOK_OUTBOUND_SECRET if secret is None else secret
        configured_api_key = settings.HEAR_API_KEY if api_key is None else api_key
        self._api_key = configured_api_key.strip()
        self._secret = (configured_secret or self._api_key).strip()
        self._pool = pool or HttpPool(timeout_ms=settings.HEAR_EVENT_WEBHOOK_TIMEOUT_MS)

    @property
    def enabled(self) -> bool:
        return bool(self._url and self._api_key and self._secret)

    async def send(self, envelope: dict) -> bool:
        if not self.enabled:
            return False
        body = json.dumps(envelope, separators=(",", ":"))
        try:
            response = await self._pool.get().post(
                self._url,
                content=body,
                headers=EventUtils.webhook_headers(
                    body,
                    self._secret,
                    self._api_key,
                ),
            )
            if 200 <= response.status_code < 300:
                return True
            self.logger.error(
                "Hear outbound webhook rejected event=%s status=%s",
                envelope.get("event"),
                response.status_code,
            )
            return False
        except HttpCircuitOpen:
            self.logger.warning(
                "Hear outbound webhook deferred event=%s reason=circuit_open",
                envelope.get("event"),
            )
            return False
        except Exception:
            self.logger.exception("Hear outbound webhook failed event=%s", envelope.get("event"))
            return False
