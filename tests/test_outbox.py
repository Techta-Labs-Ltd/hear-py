from unittest.mock import AsyncMock

import pytest

from src.database.dynamodb import DynamoExpressions
from src.services.outbox import OutboxRelayService


class Producer:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.envelopes = []

    def send(self, envelope: dict) -> bool:
        self.envelopes.append(envelope)
        return self.accepted


class Table:
    partition_key = "id"
    sort_key = "scope"

    def __init__(self, items=None) -> None:
        self.update_item = AsyncMock()
        self.query = AsyncMock(return_value={"items": items or []})


def _envelope() -> dict:
    return {
        "event": "feedback.given",
        "schemaVersion": 3,
        "eventId": "feedback:listener-1:track-1:enjoyed",
        "timestamp": "2026-09-15T00:00:00Z",
        "data": {
            "action": "alexa",
            "alexaUserId": "alexa-user",
            "listenerId": "listener-1",
            "clientEventId": "feedback:listener-1:track-1:enjoyed",
        },
    }


def _item() -> dict:
    return {
        "id": "listener:development:listener-1",
        "scope": "OUTBOX#feedback:listener-1:track-1:enjoyed",
        "recordType": "OUTBOX",
        "outboxStatus": "PENDING",
        "eventId": "feedback:listener-1:track-1:enjoyed",
        "envelope": _envelope(),
    }


@pytest.mark.asyncio
async def test_relay_sends_committed_outbox_record_and_marks_it_sent():
    table = Table()
    producer = Producer()
    record = {
        "eventID": "stream-1",
        "eventName": "INSERT",
        "dynamodb": {"NewImage": {key: DynamoExpressions.encode_value(value) for key, value in _item().items()}},
    }

    result = await OutboxRelayService(table, producer).relay([record])

    assert result == {"batchItemFailures": []}
    assert producer.envelopes == [_envelope()]
    table.update_item.assert_awaited_once()
    assert table.update_item.call_args.args[:2] == (
        "listener:development:listener-1",
        "OUTBOX#feedback:listener-1:track-1:enjoyed",
    )


@pytest.mark.asyncio
async def test_relay_retries_the_stream_record_when_queue_acceptance_fails():
    table = Table()
    record = {
        "eventID": "stream-1",
        "eventName": "INSERT",
        "dynamodb": {"NewImage": {key: DynamoExpressions.encode_value(value) for key, value in _item().items()}},
    }

    result = await OutboxRelayService(table, Producer(accepted=False)).relay([record])

    assert result == {"batchItemFailures": [{"itemIdentifier": "stream-1"}]}
    table.update_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_queries_only_the_bounded_pending_outbox_index():
    item = _item()
    table = Table([item])
    producer = Producer()

    delivered = await OutboxRelayService(table, producer).recover_pending(limit=4)

    assert delivered == 1
    table.query.assert_awaited_once_with(
        "PENDING",
        index_name="outboxKey-createdAt-index",
        partition_key="outboxKey",
        limit=4,
        ascending=True,
    )
