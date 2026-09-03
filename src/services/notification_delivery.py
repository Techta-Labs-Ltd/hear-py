from __future__ import annotations

import logging

from src.utils.notifications import NotificationInboxItem, NotificationStreamDecoder


class NotificationDeliveryService:
    logger = logging.getLogger(__name__)
    __slots__ = ("_inbox", "_proactive")

    def __init__(self, inbox, proactive) -> None:
        self._inbox = inbox
        self._proactive = proactive

    async def consume(self, records: list[dict]) -> dict:
        failures = []
        for record in records:
            sequence_number = str(
                ((record.get("dynamodb") or {}).get("SequenceNumber") or "")
            )
            try:
                retryable = await self._consume_record(record)
            except Exception as exc:
                self.logger.warning(
                    "Hear: proactive notification record failed error=%s",
                    type(exc).__name__,
                )
                retryable = True
            if retryable and sequence_number:
                failures.append({"itemIdentifier": sequence_number})
        return {"batchItemFailures": failures}

    async def _consume_record(self, record: dict) -> bool:
        if record.get("eventName") != "INSERT":
            return False
        raw = (record.get("dynamodb") or {}).get("NewImage") or {}
        item = NotificationInboxItem.normalize(NotificationStreamDecoder.item(raw))
        if not item:
            self.logger.warning("Hear: invalid notification stream record ignored")
            return False
        listener_id = item["listenerId"]
        notification_id = item["notificationId"]
        if not item.get("sendProactive", True):
            await self._inbox.set_delivery(
                listener_id,
                notification_id,
                "suppressed",
                error_code="send_proactive_disabled",
            )
            return False
        result = await self._proactive.deliver(item)
        if result.get("sent"):
            await self._inbox.set_delivery(
                listener_id,
                notification_id,
                "sent",
                http_status=result.get("httpStatus"),
            )
            self.logger.info("Hear: proactive notification delivered")
            return False
        status = "retrying" if result.get("retryable") else "failed"
        await self._inbox.set_delivery(
            listener_id,
            notification_id,
            status,
            http_status=result.get("httpStatus"),
            error_code=result.get("errorCode"),
        )
        self.logger.warning(
            "Hear: proactive notification delivery failed retryable=%s httpStatus=%s error=%s",
            bool(result.get("retryable")),
            result.get("httpStatus"),
            result.get("errorCode"),
        )
        return bool(result.get("retryable"))
