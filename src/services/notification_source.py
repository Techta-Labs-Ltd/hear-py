"""AWS source-event adapter. Go owns audience ranking; the existing Lambda owns Amazon delivery."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Literal
from uuid import UUID, uuid4

import boto3
from botocore.config import Config
from pydantic import BaseModel, ConfigDict, Field

from config import settings
from src.clients.hear import HearApiClient
from src.database.dynamodb import DynamoExpressions, DynamoTable
from src.services.logging_control import ApplicationLog
from src.utils.deadline import RequestDeadline
from src.utils.events import SqsBatch


class SourceCursor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    listenerId: UUID
    rank: Literal[30, 90, 100, 110]


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
            if body.get("source") != "hear.notifications" or body.get("detail-type") != "AlexaNotificationSourceReady":
                raise ValueError("unexpected_source_event")
            detail = body["detail"]
            if not isinstance(detail, dict) or detail.get("eventId") != f"alexa-source:{detail.get('notificationId')}":
                raise ValueError("invalid_source_event_id")
            body = {"schemaVersion": detail.get("schemaVersion"), "notificationId": detail.get("notificationId"), "environment": environment}
        command = cls.model_validate(body)
        if command.environment != environment:
            raise ValueError("source_environment_mismatch")
        return command

    def receipt_key(self) -> str:
        value = {"environment": self.environment, "notificationId": self.notificationId, "after": self.after.model_dump(mode="json") if self.after else None}
        return "NOTIFICATION_SOURCE#" + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class SourceCandidatePage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SourceCursor] = Field(max_length=100)
    nextCursor: SourceCursor | None = None


class SourcePageReceipts:
    SCOPE = "NOTIFICATION_SOURCE_PAGE"

    def __init__(self, table: DynamoTable) -> None:
        self.table = table

    async def acquire(self, command: SourceCommand) -> str | None:
        key = command.receipt_key()
        item = await self.table.get_item(key, self.SCOPE)
        if item and item.get("state") == "done":
            return None
        token = str(uuid4())
        now = int(time.time())
        await self.table.update_item(
            key, self.SCOPE,
            updates={"recordType": self.SCOPE, "state": "processing", "leaseToken": token, "leaseUntil": now + 120, "expiresAt": now + 30 * 86400},
            condition=[
                {"op": "or", "rules": [DynamoExpressions.not_exists("state"), DynamoExpressions.eq("state", "processing")]},
                {"op": "or", "rules": [DynamoExpressions.not_exists("leaseUntil"), {"op": "<", "name": "leaseUntil", "value": now}]},
            ],
        )
        return token

    async def finish(self, command: SourceCommand, token: str) -> None:
        await self.table.update_item(
            command.receipt_key(), self.SCOPE, updates={"state": "done", "leaseUntil": 0},
            condition=[DynamoExpressions.eq("leaseToken", token)],
        )

    async def release(self, command: SourceCommand, token: str) -> None:
        await self.table.update_item(
            command.receipt_key(), self.SCOPE, updates={"leaseUntil": 0},
            condition=[DynamoExpressions.eq("leaseToken", token), DynamoExpressions.eq("state", "processing")],
        )


class SourceQueueRelay:
    def __init__(self, client: Any = None) -> None:
        self.client: Any = client or boto3.client("sqs", region_name=settings.AWS_REGION, config=Config(connect_timeout=1, read_timeout=2, retries={"max_attempts": 0}))

    async def send(self, queue_url: str, values: list[dict], deadline: RequestDeadline) -> None:
        if not queue_url:
            raise RuntimeError("source_queue_not_configured")
        for start in range(0, len(values), 10):
            if deadline.remaining_ms(1500) < 3500:
                raise TimeoutError("source_page_deadline")
            entries = [{"Id": str(i), "MessageBody": json.dumps(value, separators=(",", ":"))} for i, value in enumerate(values[start:start + 10])]
            response = await asyncio.to_thread(self.client.send_message_batch, QueueUrl=queue_url, Entries=entries)
            successful = {item.get("Id") for item in response.get("Successful", [])}
            if response.get("Failed") or successful != {entry["Id"] for entry in entries}:
                raise RuntimeError("source_queue_partial_failure")


class NotificationSourceService:
    def __init__(self, api: Any = None, receipts: Any = None, relay: Any = None) -> None:
        self.api = api or HearApiClient()
        self.receipts = receipts or SourcePageReceipts(DynamoTable(
            settings.dynamo_table, partition_key=settings.HEAR_DDB_PARTITION_KEY,
            sort_key=settings.HEAR_DDB_SORT_KEY, region=settings.ddb_region,
        ))
        self.relay = relay or SourceQueueRelay()

    async def consume(self, records: list[dict], *, deadline: RequestDeadline) -> dict:
        ids = SqsBatch.message_ids(records)
        failed = []
        for record, message_id in zip(records, ids):
            command = None
            token = None
            try:
                if not settings.HEAR_NOTIFICATION_SOURCE_QUEUE_URL or not settings.HEAR_NOTIFICATION_DELIVERY_QUEUE_URL:
                    raise RuntimeError("source_queues_not_configured")
                if deadline.remaining_ms(1500) < 8000:
                    raise TimeoutError("source_page_deadline")
                command = SourceCommand.decode(record, settings.STAGE)
                token = await self.receipts.acquire(command)
                if token is None:
                    continue
                size = max(1, min(100, settings.HEAR_NOTIFICATION_SOURCE_PAGE_SIZE))
                request = {"environment": command.environment, "notificationId": command.notificationId, "limit": size}
                if command.after:
                    request["after"] = command.after.model_dump(mode="json")
                page = SourceCandidatePage.model_validate(await self.api.notification_source_candidates(request))
                if len(page.items) > size or len({item.listenerId for item in page.items}) != len(page.items):
                    raise ValueError("invalid_source_audience_page")
                previous = (-command.after.rank, command.after.listenerId.int) if command.after else None
                for candidate in page.items:
                    current = (-candidate.rank, candidate.listenerId.int)
                    if previous is not None and current <= previous:
                        raise ValueError("non_advancing_source_audience")
                    previous = current
                if page.nextCursor and (not page.items or page.nextCursor != page.items[-1] or page.nextCursor == command.after):
                    raise ValueError("non_advancing_source_cursor")
                recipients = [{"schemaVersion": 1, "notificationId": command.notificationId, "listenerId": str(item.listenerId)} for item in page.items]
                # Go returns explicit followers first. The existing recipient
                # SQS/Lambda protocol remains unchanged; no Amazon API here.
                await self.relay.send(settings.HEAR_NOTIFICATION_DELIVERY_QUEUE_URL, recipients, deadline)
                if page.nextCursor:
                    continuation = SourceCommand(schemaVersion=1, environment=command.environment, notificationId=command.notificationId,
                                                 after=page.nextCursor, pageNumber=command.pageNumber + 1)
                    await self.relay.send(settings.HEAR_NOTIFICATION_SOURCE_QUEUE_URL, [continuation.model_dump(mode="json", exclude_none=True)], deadline)
                await self.receipts.finish(command, token)
            except Exception as exc:
                if command is not None and token is not None:
                    try:
                        await self.receipts.release(command, token)
                    except Exception:
                        pass  # The bounded durable lease remains recoverable.
                ApplicationLog.warning("Source notification page failed error=%s", type(exc).__name__)
                failed.append({"itemIdentifier": message_id})
        return {"batchItemFailures": failed}
