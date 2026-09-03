from __future__ import annotations

import time
from typing import Any

from src.constants.notifications import NotificationConstants
from src.database.dynamodb import DynamoTable
from src.utils.notifications import NotificationInboxItem


class NullNotificationInbox:
    __slots__ = ()

    @property
    def enabled(self) -> bool:
        return False

    async def pending(self, listener_id: str, limit: int = 5) -> list[dict]:
        del listener_id, limit
        return []

    async def set_status(
        self, listener_id: str, notification_id: str, status: str
    ) -> None:
        del listener_id, notification_id, status

    async def set_delivery(
        self,
        listener_id: str,
        notification_id: str,
        status: str,
        *,
        http_status: int | None = None,
        error_code: str | None = None,
    ) -> None:
        del listener_id, notification_id, status, http_status, error_code


class DynamoNotificationInbox:
    __slots__ = ("_table",)

    def __init__(self, table_name: str, *, region: str | None = None) -> None:
        self._table = DynamoTable(
            table_name,
            partition_key="listenerId",
            sort_key="notificationId",
            region=region,
        )

    @property
    def enabled(self) -> bool:
        return True

    async def pending(self, listener_id: str, limit: int = 5) -> list[dict]:
        response = await self._table.query(
            listener_id,
            index_name=NotificationConstants.ACTIVE_INDEX,
            partition_key=NotificationConstants.ACTIVE_PARTITION_KEY,
            consistent=False,
            ascending=False,
            limit=max(25, int(limit) * 4),
        )
        now = int(time.time())
        items = [
            normalized
            for item in response.get("items") or []
            if (normalized := NotificationInboxItem.normalize(item))
            and normalized.get("status") in NotificationConstants.ACTIVE_STATUSES
            and (
                normalized.get("expiresAt") is None
                or int(normalized["expiresAt"]) > now
            )
        ]
        return items[: max(1, int(limit))]

    async def set_status(
        self, listener_id: str, notification_id: str, status: str
    ) -> None:
        normalized_status = str(status or "").strip().casefold()
        if normalized_status not in (
            NotificationConstants.ACTIVE_STATUSES
            | NotificationConstants.TERMINAL_STATUSES
        ):
            raise ValueError(f"unsupported notification status: {status}")
        updates: dict[str, Any] = {
            "status": normalized_status,
            "updatedAt": int(time.time()),
        }
        removes: list[str] = []
        if normalized_status in NotificationConstants.ACTIVE_STATUSES:
            item = await self._table.get_item(listener_id, notification_id)
            normalized = NotificationInboxItem.normalize(item)
            if not normalized:
                return
            updates.update(
                {
                    NotificationConstants.ACTIVE_PARTITION_KEY: listener_id,
                    NotificationConstants.ACTIVE_SORT_KEY: NotificationInboxItem.active_sort_key(
                        normalized
                    ),
                }
            )
        else:
            removes.extend(
                [
                    NotificationConstants.ACTIVE_PARTITION_KEY,
                    NotificationConstants.ACTIVE_SORT_KEY,
                ]
            )
        await self._table.update_item(
            listener_id,
            notification_id,
            updates=updates,
            removes=removes,
            condition=[{"op": "exists", "name": "notificationId"}],
        )

    async def set_delivery(
        self,
        listener_id: str,
        notification_id: str,
        status: str,
        *,
        http_status: int | None = None,
        error_code: str | None = None,
    ) -> None:
        updates = {
            "deliveryStatus": str(status or "failed"),
            "deliveryUpdatedAt": int(time.time()),
        }
        if http_status is not None:
            updates["deliveryHttpStatus"] = int(http_status)
        if error_code:
            updates["deliveryErrorCode"] = str(error_code)[:120]
        await self._table.update_item(
            listener_id,
            notification_id,
            updates=updates,
            condition=[{"op": "exists", "name": "notificationId"}],
        )


class NotificationInboxFactory:
    __slots__ = ()

    @staticmethod
    def build(table_name: str, *, region: str | None = None):
        normalized = str(table_name or "").strip()
        return (
            DynamoNotificationInbox(normalized, region=region)
            if normalized
            else NullNotificationInbox()
        )
