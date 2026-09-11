from __future__ import annotations

import logging

from src.utils.notifications import NotificationItem, NotificationQueueMessage


class NotificationDeliveryService:
    logger = logging.getLogger(__name__)
    __slots__ = ("_notification_api", "_proactive")

    def __init__(self, notification_api, proactive) -> None:
        self._notification_api = notification_api
        self._proactive = proactive

    async def consume(self, records: list[dict]) -> dict:
        failures = []
        for record in records:
            message_id = str(record.get("messageId") or "")
            try:
                retryable = await self._consume_record(record)
            except Exception as exc:
                self.logger.warning(
                    "Hear: proactive notification record failed error=%s",
                    type(exc).__name__,
                )
                retryable = True
            if retryable and message_id:
                failures.append({"itemIdentifier": message_id})
        return {"batchItemFailures": failures}

    async def _consume_record(self, record: dict) -> bool:
        message = NotificationQueueMessage.decode(record)
        if not message:
            self.logger.warning("Hear: invalid notification queue record")
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
            return bool(fetch.get("retryable"))
        items = fetch.get("items") or []
        if not items:
            return False
        item = NotificationItem.normalize(items[0])
        if not item or item.get("listenerId") != message["listenerId"]:
            self.logger.warning("Hear: invalid notification API response")
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
            return not update.get("updated") and bool(update.get("retryable"))
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
                return bool(update.get("retryable"))
            self.logger.info("Hear: proactive notification delivered")
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
        self.logger.warning(
            "Hear: proactive notification delivery failed retryable=%s httpStatus=%s error=%s",
            bool(result.get("retryable")),
            result.get("httpStatus"),
            result.get("errorCode"),
        )
        return bool(result.get("retryable")) or (
            not update.get("updated") and bool(update.get("retryable"))
        )
