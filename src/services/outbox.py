from __future__ import annotations

import time

from src.clients.events import BackendEventEnvelope, SqsEventClient
from src.database.dynamodb import DynamoExpressions, DynamoTable
from src.services.logging_control import ApplicationLog


class OutboxRelayService:
    """Relays committed DynamoDB outbox records to the existing outbound queue."""

    _PENDING = "PENDING"
    _SENT = "SENT"

    def __init__(self, table: DynamoTable, producer: SqsEventClient) -> None:
        self._table = table
        self._producer = producer

    @staticmethod
    def _record_item(record: dict) -> dict | None:
        if not isinstance(record, dict) or record.get("eventName") not in {"INSERT", "MODIFY"}:
            return None
        image = (record.get("dynamodb") or {}).get("NewImage")
        item = DynamoExpressions.decode_item(image) if isinstance(image, dict) else None
        if not isinstance(item, dict) or item.get("recordType") != "OUTBOX":
            return None
        if item.get("outboxStatus") != OutboxRelayService._PENDING:
            return None
        return item

    async def _deliver(self, item: dict) -> bool:
        envelope = item.get("envelope")
        event_id = str(item.get("eventId") or "").strip()
        listener_id = item.get(self._table.partition_key)
        scope = item.get(self._table.sort_key or "scope")
        if not event_id or not listener_id or not scope or not isinstance(envelope, dict):
            return False
        try:
            BackendEventEnvelope.model_validate(envelope)
        except Exception:
            ApplicationLog.warning("Outbox record rejected event_id=%s", event_id)
            return False
        if not self._producer.send(envelope):
            return False
        try:
            await self._table.update_item(
                listener_id,
                scope,
                updates={"outboxStatus": self._SENT, "sentAt": int(time.time() * 1000)},
                condition=[DynamoExpressions.eq("outboxStatus", self._PENDING)],
            )
            return True
        except Exception:
            # Queue acceptance with an uncertain status update is deliberately retried.
            ApplicationLog.warning("Outbox acknowledgement deferred event_id=%s", event_id)
            return False

    async def relay(self, records: list[dict]) -> dict:
        failures = []
        for record in records if isinstance(records, list) else []:
            item = self._record_item(record)
            if item is None:
                continue
            if not await self._deliver(item):
                identifier = record.get("eventID") or record.get("eventId")
                if identifier:
                    failures.append({"itemIdentifier": str(identifier)})
                else:
                    raise ValueError("DynamoDB outbox stream record requires eventID")
        return {"batchItemFailures": failures}

    async def recover_pending(self, *, limit: int) -> int:
        """Bounded GSI recovery for records missed by the stream relay."""
        response = await self._table.query(
            self._PENDING,
            index_name="outboxKey-createdAt-index",
            partition_key="outboxKey",
            limit=max(1, limit),
            ascending=True,
        )
        delivered = 0
        for item in response.get("items") or []:
            if isinstance(item, dict) and await self._deliver(item):
                delivered += 1
        return delivered
