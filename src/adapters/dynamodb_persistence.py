from __future__ import annotations

import logging
import time

from src.adapters.dynamodb import (
    DynamoTable,
    encode_value,
    eq,
    item_bytes,
    not_exists,
)
from src.adapters.persistence_user_id import resolve_persistence_user_id
from config import settings

logger = logging.getLogger(__name__)

_VERSION_FIELD = "_persistenceVersion"
_SIZE_WARN_BYTES = 65536


class InvalidPersistenceKey(ValueError):
    pass


def _is_invalid_key(user_id: str) -> bool:
    if not user_id or not user_id.strip():
        return True
    if user_id.startswith("__"):
        return True
    return user_id.startswith("session:")


class DynamoDbPersistenceAdapter:
    def __init__(
        self,
        table_name: str,
        partition_key_name: str = "id",
        attributes_name: str = "attributes",
        region: str | None = None,
        ttl_attribute: str = "expiresAt",
        ttl_days: int | None = None,
    ) -> None:
        if not table_name:
            raise ValueError("DynamoDbPersistenceAdapter: table_name is required")
        self.table_name = table_name
        self.partition_key_name = partition_key_name
        self.attributes_name = attributes_name
        self.ttl_attribute = ttl_attribute
        self.ttl_days = ttl_days or settings.HEAR_PERSISTENCE_TTL_DAYS
        self._table = DynamoTable(
            table_name=table_name,
            partition_key=partition_key_name,
            region=region or settings.ddb_region,
        )

    def _user_id(self, request_envelope: dict) -> str:
        user_id = resolve_persistence_user_id(request_envelope)
        if _is_invalid_key(user_id):
            raise InvalidPersistenceKey(f"invalid persistence key {user_id!r}")
        return user_id

    async def get_attributes(self, request_envelope: dict) -> dict:
        user_id = self._user_id(request_envelope)
        item = await self._table.get_item(user_id)
        if not item or self.attributes_name not in item:
            return {}
        attributes = item[self.attributes_name] or {}
        attributes[_VERSION_FIELD] = int(item.get("stateVersion") or 0)
        return attributes

    async def save_attributes(self, request_envelope: dict, attributes: dict) -> None:
        user_id = self._user_id(request_envelope)
        expires_at = int(time.time()) + (self.ttl_days or 180) * 86400
        document = dict(attributes or {})
        expected_version = int(document.pop(_VERSION_FIELD, 0) or 0)
        size = item_bytes(encode_value(document))
        if size > _SIZE_WARN_BYTES:
            logger.warning(
                "DynamoDB state item oversized bytes=%s table=%s",
                size,
                self.table_name,
            )
        if expected_version == 0:
            condition = [not_exists("stateVersion")]
        else:
            condition = [eq("stateVersion", expected_version)]
        await self._table.update_item(
            user_id,
            updates={
                self.attributes_name: document,
                self.ttl_attribute: expires_at,
                "stateVersion": expected_version + 1,
            },
            condition=condition,
        )

    async def delete_attributes(self, request_envelope: dict) -> None:
        user_id = self._user_id(request_envelope)
        await self._table.delete_item(user_id)


def build_dynamo_adapter(
    table_name: str | None = None,
    region: str | None = None,
) -> DynamoDbPersistenceAdapter:
    return DynamoDbPersistenceAdapter(
        table_name=table_name or settings.dynamo_table,
        region=region or settings.ddb_region,
        ttl_days=settings.HEAR_PERSISTENCE_TTL_DAYS,
    )
