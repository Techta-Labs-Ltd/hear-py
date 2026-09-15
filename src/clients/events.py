from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

import boto3
from pydantic import BaseModel, ConfigDict, Field, field_validator

from config import settings
from src.clients.pool import HttpCircuitOpen, HttpPool
from src.services.logging_control import ApplicationLog
from src.utils.events import EventUtils


class EventTrackListening(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    contentId: str = Field(min_length=1)
    trackIndex: int | None = Field(default=None, ge=0)
    durationMs: int | None = Field(default=None, ge=0)
    listenedMs: int | None = Field(default=None, ge=0)
    timeSpentMs: int | None = Field(default=None, ge=0)
    completed: bool | None = None

    @field_validator("*", mode="before")
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("Omit unavailable event fields instead of sending null")
        return value


class BackendEventData(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    action: Literal["alexa"]
    alexaUserId: str = Field(min_length=1)
    clientEventId: str = Field(min_length=1)
    listenerId: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None
    permissionGranted: bool | None = None
    subjectType: Literal["content", "publication", "creator"] | None = None
    subjectId: str | None = Field(default=None, min_length=1)
    contentId: str | None = Field(default=None, min_length=1)
    publicationId: str | None = Field(default=None, min_length=1)
    sourceType: Literal["creator", "organization"] | None = None
    sourceId: str | None = Field(default=None, min_length=1)
    sessionId: str | None = Field(default=None, min_length=1)
    subjectSessionId: str | None = Field(default=None, min_length=1)
    eventType: (
        Literal[
            "started",
            "progress",
            "nearly_finished",
            "paused",
            "resumed",
            "stopped",
            "finished",
            "failed",
        ]
        | None
    ) = None
    positionMs: int | None = Field(default=None, ge=0)
    durationMs: int | None = Field(default=None, ge=0)
    listenedMs: int | None = Field(default=None, ge=0)
    timeSpentMs: int | None = Field(default=None, ge=0)
    trackIndex: int | None = Field(default=None, ge=0)
    trackCount: int | None = Field(default=None, ge=0)
    feedback: Literal["enjoyed", "somewhat", "not_enjoyed", "skipped"] | None = None
    trackListening: list[EventTrackListening] | None = None
    timestamp: int | None = Field(default=None, ge=0)
    timestampMs: int | None = Field(default=None, ge=0)

    @field_validator("*", mode="before")
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("Omit unavailable event fields instead of sending null")
        return value


class BackendEventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event: Literal[
        "playback.started",
        "playback.progress",
        "playback.nearly_finished",
        "playback.paused",
        "playback.resumed",
        "playback.stopped",
        "playback.finished",
        "playback.failed",
        "feedback.given",
        "user.followed_creator",
        "user.unfollowed_creator",
        "user.followed_organization",
        "user.unfollowed_organization",
        "notifications.enabled",
        "notifications.disabled",
        "user.reported_content",
        "user.reported_creator",
    ]
    schemaVersion: Literal[3]
    eventId: str = Field(min_length=1)
    timestamp: str
    data: BackendEventData

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or "T" not in value.upper():
            raise ValueError("Event timestamp must include a date, time and timezone")
        return value


class SqsEventClient:
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
            ApplicationLog.exception(
                "Hear outbound SQS dispatch failed event=%s", envelope.get("event")
            )
            return False


class WebhookEventClient:
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
            ApplicationLog.error(
                "Hear outbound webhook rejected event=%s status=%s",
                envelope.get("event"),
                response.status_code,
            )
            return False
        except HttpCircuitOpen:
            ApplicationLog.warning(
                "Hear outbound webhook deferred event=%s reason=circuit_open",
                envelope.get("event"),
            )
            return False
        except Exception:
            ApplicationLog.exception("Hear outbound webhook failed event=%s", envelope.get("event"))
            return False
