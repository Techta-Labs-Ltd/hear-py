from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from config import settings
from src.services.notification_source import (
    NotificationSourceService,
    SourceCommand,
    SourcePageReceipts,
    SourceQueueRelay,
)
from src.utils.deadline import RequestDeadline


def budget(milliseconds=30000):
    return RequestDeadline.from_context(SimpleNamespace(get_remaining_time_in_millis=lambda: milliseconds))


def event():
    return {"messageId": "source-1", "body": json.dumps({
        "source": "hear.notifications", "detail-type": "AlexaNotificationSourceReady",
        "detail": {"schemaVersion": 1, "notificationId": "creator:source:revision", "eventId": "alexa-source:creator:source:revision"},
    })}


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    monkeypatch.setattr(settings, "STAGE", "development")
    monkeypatch.setattr(settings, "HEAR_NOTIFICATION_SOURCE_QUEUE_URL", "source-test-queue")
    monkeypatch.setattr(settings, "HEAR_NOTIFICATION_DELIVERY_QUEUE_URL", "recipient-test-queue")


def service(page):
    api = SimpleNamespace(notification_source_candidates=AsyncMock(return_value=page))
    receipts = SimpleNamespace(acquire=AsyncMock(return_value="lease"), finish=AsyncMock(), release=AsyncMock())
    relay = SimpleNamespace(send=AsyncMock())
    return NotificationSourceService(api, receipts, relay)


@pytest.mark.asyncio
async def test_source_event_uses_go_ranked_page_and_existing_recipient_protocol():
    items = [{"listenerId": str(uuid4()), "rank": 110}, {"listenerId": str(uuid4()), "rank": 30}]
    s = service({"items": items, "nextCursor": items[-1]})
    result = await s.consume([event()], deadline=budget())
    assert result == {"batchItemFailures": []}
    s.api.notification_source_candidates.assert_awaited_once_with({
        "environment": "development", "notificationId": "creator:source:revision", "limit": 100,
    })
    calls = s.relay.send.await_args_list
    assert calls[0].args[0] == "recipient-test-queue"
    assert calls[0].args[1] == [
        {"schemaVersion": 1, "notificationId": "creator:source:revision", "listenerId": item["listenerId"]} for item in items
    ]
    assert calls[1].args[0] == "source-test-queue"
    assert calls[1].args[1][0]["after"] == items[-1]
    assert calls[1].args[1][0]["environment"] == "development"
    s.receipts.finish.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_source_page_is_acknowledged_without_dispatch():
    s = service({"items": [], "nextCursor": None})
    s.receipts.acquire.return_value = None
    assert await s.consume([event()], deadline=budget()) == {"batchItemFailures": []}
    s.api.notification_source_candidates.assert_not_awaited()
    s.relay.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_dispatch_failure_preserves_source_for_retry():
    s = service({"items": [{"listenerId": str(uuid4()), "rank": 30}], "nextCursor": None})
    s.relay.send.side_effect = RuntimeError("queue outage")
    assert await s.consume([event()], deadline=budget()) == {"batchItemFailures": [{"itemIdentifier": "source-1"}]}
    s.receipts.finish.assert_not_awaited()
    s.receipts.release.assert_awaited_once()


@pytest.mark.asyncio
async def test_out_of_order_ranked_page_is_rejected():
    s = service({"items": [{"listenerId": str(uuid4()), "rank": 30}, {"listenerId": str(uuid4()), "rank": 110}], "nextCursor": None})
    assert (await s.consume([event()], deadline=budget()))["batchItemFailures"]
    s.relay.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_exhausted_lambda_budget_does_not_claim_source_page():
    s = service({"items": [], "nextCursor": None})
    assert (await s.consume([event()], deadline=budget(0)))["batchItemFailures"]
    s.receipts.acquire.assert_not_awaited()


def test_cross_environment_continuation_is_rejected():
    record = {"body": json.dumps({"schemaVersion": 1, "notificationId": "one", "environment": "production"})}
    with pytest.raises(ValueError):
        SourceCommand.decode(record, "development")


@pytest.mark.asyncio
async def test_done_dynamo_receipt_does_not_reacquire_lease():
    table = SimpleNamespace(get_item=AsyncMock(return_value={"state": "done"}), update_item=AsyncMock())
    store = SourcePageReceipts(table)
    assert await store.acquire(SourceCommand.decode(event(), "development")) is None
    table.update_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_receipt_claim_is_conditional_and_fenced():
    table = SimpleNamespace(get_item=AsyncMock(return_value=None), update_item=AsyncMock())
    store = SourcePageReceipts(table)
    command = SourceCommand.decode(event(), "development")
    token = await store.acquire(command)
    claim = table.update_item.await_args.kwargs
    assert claim["updates"]["leaseToken"] == token
    assert claim["condition"][1]["op"] == "or"
    await store.finish(command, token)
    assert table.update_item.await_args.kwargs["condition"] == [{"op": "=", "name": "leaseToken", "value": token}]


@pytest.mark.asyncio
async def test_sqs_http_success_with_partial_failure_is_not_success():
    client = MagicMock()
    client.send_message_batch.return_value = {"Successful": [], "Failed": [{"Id": "0"}]}
    with pytest.raises(RuntimeError, match="partial_failure"):
        await SourceQueueRelay(client).send("test", [{"schemaVersion": 1}], budget())
