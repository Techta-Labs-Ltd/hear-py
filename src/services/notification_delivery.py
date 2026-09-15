from __future__ import annotations

import asyncio
from src.services.logging_control import ApplicationLog

from src.utils.deadline import RequestDeadline
from src.utils.events import SqsBatch
from src.utils.notifications import NotificationItem, NotificationQueueMessage


class NotificationDeliveryService:
    __slots__ = ("_notification_api", "_proactive")

    def __init__(self, notification_api, proactive) -> None:
        self._notification_api = notification_api
        self._proactive = proactive

    async def consume(
        self, records: list[dict], *, deadline: RequestDeadline | None = None
    ) -> dict:
        message_ids = SqsBatch.message_ids(records)
        budget = deadline if deadline is not None else RequestDeadline.from_context(None)
        failures = []
        for record, message_id in zip(records, message_ids):
            try:
                remaining_ms = budget.remaining_ms(300)
                retryable = remaining_ms <= 0 or await asyncio.wait_for(
                    self._consume_record(record), timeout=remaining_ms / 1000.0
                )
            except Exception as exc:
                ApplicationLog.warning(
                    "Hear: proactive notification record failed error=%s",
                    type(exc).__name__,
                )
                retryable = True
            if retryable:
                failures.append({"itemIdentifier": message_id})
        return {"batchItemFailures": failures}

    async def _consume_record(self, record: dict) -> bool:
        message = NotificationQueueMessage.decode(record)
        if not message:
            ApplicationLog.warning("Hear: invalid notification queue record")
            return True
        fetch = await self._notification_api.pending(
            {
                "listenerId": message["listenerId"],
                "notificationId": message["notificationId"],
                "purpose": "delivery",
                "limit": 1,
            }
        )
        if fetch.get("failed"):
            return True
        items = fetch.get("items") or []
        if not items:
            return False
        item = NotificationItem.normalize(items[0])
        if (
            not item
            or item.get("listenerId") != message["listenerId"]
            or item.get("notificationId") != message["notificationId"]
        ):
            ApplicationLog.warning("Hear: invalid notification API response")
            return True
        listener_id = item["listenerId"]
        notification_id = item["notificationId"]
        if not item.get("sendProactive", True):
            update = await self._notification_api.update(
                {
                    "listenerId": listener_id,
                    "notificationId": notification_id,
                    "deliveryStatus": "suppressed",
                    "deliveryErrorCode": "send_proactive_disabled",
                }
            )
            return not update.get("updated")
        result = await self._proactive.deliver(item)
        if result.get("sent"):
            update = await self._notification_api.update(
                {
                    "listenerId": listener_id,
                    "notificationId": notification_id,
                    "deliveryStatus": "sent",
                    "deliveryHttpStatus": result.get("httpStatus"),
                }
            )
            if not update.get("updated"):
                return True
            ApplicationLog.info("Hear: proactive notification delivered")
            return False
        status = "retrying" if result.get("retryable") else "failed"
        update = await self._notification_api.update(
            {
                "listenerId": listener_id,
                "notificationId": notification_id,
                "deliveryStatus": status,
                "deliveryHttpStatus": result.get("httpStatus"),
                "deliveryErrorCode": result.get("errorCode"),
            }
        )
        ApplicationLog.warning(
            "Hear: proactive notification delivery failed retryable=%s httpStatus=%s error=%s",
            bool(result.get("retryable")),
            result.get("httpStatus"),
            result.get("errorCode"),
        )
        return bool(result.get("retryable")) or not update.get("updated")
