from __future__ import annotations

import time
from typing import Any

from config import settings
from src.database.dynamodb import DynamoExpressions, DynamoTable
from src.models.user import User


class AlexaNotificationRecipientDirectory:
    SCOPE = "NOTIFICATION_RECIPIENT"

    def __init__(self, table: DynamoTable | None = None) -> None:
        self._table = table
        if self._table is None and settings.HEAR_DDB_TABLE:
            self._table = DynamoTable(
                settings.dynamo_table,
                partition_key=settings.HEAR_DDB_PARTITION_KEY,
                sort_key=settings.HEAR_DDB_SORT_KEY,
                region=settings.ddb_region,
            )

    @property
    def enabled(self) -> bool:
        return self._table is not None

    async def remember(
        self,
        *,
        listener_id: str,
        alexa_user_id: str,
        device_id: str | None = None,
        locale: str | None = None,
    ) -> bool:
        if self._table is None:
            return False
        listener = str(listener_id or "").strip()
        recipient = str(alexa_user_id or "").strip()
        if not listener or not recipient:
            return False
        now = int(time.time())
        updates: dict[str, Any] = {
            "alexaUserId": recipient,
            "updatedAt": now,
            "expiresAt": now + max(1, settings.HEAR_NOTIFICATION_RECIPIENT_TTL_DAYS) * 86_400,
        }
        # DynamoExpressions does not expose an inequality helper; use its raw
        # condition format so an unchanged recipient does not create a write.
        conditions: list[dict] = [
            DynamoExpressions.not_exists("alexaUserId"),
            DynamoExpressions.not_exists("updatedAt"),
            {"op": "<>", "name": "alexaUserId", "value": recipient},
            {
                "op": "<",
                "name": "updatedAt",
                "value": now - max(1, settings.HEAR_NOTIFICATION_RECIPIENT_REFRESH_SECONDS),
            },
        ]
        for field, value in (("deviceId", device_id), ("locale", locale)):
            text = str(value or "").strip()
            if text:
                updates[field] = text
                conditions.extend(
                    [
                        DynamoExpressions.not_exists(field),
                        {"op": "<>", "name": field, "value": text},
                    ]
                )
        try:
            await self._table.update_item(
                User.canonical_persistence_key(listener),
                self.SCOPE,
                updates=updates,
                condition=[{"op": "or", "rules": conditions}],
            )
            return True
        except Exception as exc:
            response = getattr(exc, "response", {})
            code = str(response.get("Error", {}).get("Code") or "")
            if code == "ConditionalCheckFailedException":
                return False
            raise

    async def resolve(self, listener_id: str) -> str | None:
        item = (await self.get_many([listener_id])).get(str(listener_id or "").strip())
        if item is None:
            return None
        recipient = str(item.get("alexaUserId") or "").strip()
        return recipient or None

    async def get_many(self, listener_ids: list[str]) -> dict[str, dict]:
        if self._table is None:
            return {}
        requested = list(dict.fromkeys(str(value or "").strip() for value in listener_ids if str(value or "").strip()))
        if not requested:
            return {}
        keys = [(User.canonical_persistence_key(listener_id), self.SCOPE) for listener_id in requested]
        items = await self._table.batch_get_items(keys, consistent=True)
        now = int(time.time())
        by_key = {
            str(item.get(self._table.partition_key) or ""): item
            for item in items
            if int(item.get("expiresAt") or 0) > now
            and str(item.get("alexaUserId") or "").strip()
        }
        return {
            listener_id: by_key[key]
            for listener_id, key in (
                (listener_id, User.canonical_persistence_key(listener_id))
                for listener_id in requested
            )
            if key in by_key
        }
