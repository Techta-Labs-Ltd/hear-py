from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SourceCursor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    listenerId: UUID
    rank: Literal[30, 90, 100]


class SourceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: Literal[1]
    environment: Literal["development", "production"]
    notificationId: str = Field(min_length=1, max_length=512)
    after: SourceCursor | None = None
    pageNumber: int = Field(default=0, ge=0, le=100000)

    @classmethod
    def decode(cls, record: dict, environment: str) -> SourceCommand:
        body = json.loads(record.get("body") or "")
        if not isinstance(body, dict):
            raise ValueError("invalid_source_message")
        if "detail" in body:
            if (
                body.get("source") != "hear.notifications"
                or body.get("detail-type") != "AlexaNotificationSourceReady"
            ):
                raise ValueError("unexpected_source_event")
            detail = body["detail"]
            if (
                not isinstance(detail, dict)
                or detail.get("eventId") != f"alexa-source:{detail.get('notificationId')}"
            ):
                raise ValueError("invalid_source_event_id")
            body = {
                "schemaVersion": detail.get("schemaVersion"),
                "notificationId": detail.get("notificationId"),
                "environment": environment,
            }
        command = cls.model_validate(body)
        if command.environment != environment:
            raise ValueError("source_environment_mismatch")
        return command

    def receipt_key(self) -> str:
        value = {
            "environment": self.environment,
            "notificationId": self.notificationId,
            "after": self.after.model_dump(mode="json") if self.after else None,
        }
        return (
            "NOTIFICATION_SOURCE#"
            + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        )


class SourceCandidatePage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SourceCursor] = Field(max_length=100)
    nextCursor: SourceCursor | None = None
