from __future__ import annotations

import asyncio
import json
import logging
import time
from copy import deepcopy
from dataclasses import dataclass

from botocore.exceptions import ClientError

from config import settings
from src.database.dynamodb import DynamoExpressions, DynamoTable
from src.models.user import User


class DynamoUserSupport:
    logger = logging.getLogger(__name__)
    _VERSION_FIELD = "_persistenceVersion"
    _CHANGED_FIELDS = "_persistenceChangedFields"
    _ORIGINAL_FIELDS = "_persistenceOriginal"
    _COUNTER_FIELDS = frozenset(
        {
            "launchCount",
            "playCount",
            "onboardingRetries",
            "onboardingTownAttempts",
            "onboardingTownResolverFailures",
        }
    )
    _HISTORY_LIMITS = {
        "answeredFeedbackKeys": 100,
        "feedbackAskedTokens": 100,
        "feedbackGivenTokens": 100,
        "feedbackHistory": 100,
        "playHistory": 100,
        "reportHistory": 100,
    }

    @staticmethod
    def _is_invalid_key(user_id: str) -> bool:
        if not user_id or not user_id.strip():
            return True
        if user_id.startswith("__"):
            return True
        return user_id.startswith("session:")

    @staticmethod
    def build_dynamo_adapter(
        table_name: str | None = None,
        region: str | None = None,
        partition_key_name: str | None = None,
    ) -> DynamoDbPersistenceAdapter:
        options = DynamoUserOptions(
            table_name=table_name or settings.dynamo_table,
            region=region or settings.ddb_region,
            partition_key_name=partition_key_name or settings.HEAR_DDB_PARTITION_KEY or "id",
            ttl_days=settings.HEAR_PERSISTENCE_TTL_DAYS,
            conditional_writes=settings.HEAR_PERSISTENCE_CONDITIONAL,
        )
        return DynamoDbPersistenceAdapter(options)

    @staticmethod
    def is_conditional_failure(error: ClientError) -> bool:
        return error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"

    @staticmethod
    def merge_conflict(
        latest: dict, requested: dict, original: dict, changed_fields: list[str]
    ) -> dict:
        merged = deepcopy(latest)
        active_incoming = requested.get("activePlayback")
        active_latest = latest.get("activePlayback")
        incoming_playback_is_newer = (
            not isinstance(active_latest, dict)
            or not isinstance(active_incoming, dict)
            or int(active_incoming.get("eventTimestamp") or active_incoming.get("updatedAt") or 0)
            >= int(active_latest.get("eventTimestamp") or active_latest.get("updatedAt") or 0)
        )
        for field in changed_fields:
            incoming = deepcopy(requested.get(field))
            previous = original.get(field)
            current = latest.get(field)
            if (
                field in DynamoUserSupport._COUNTER_FIELDS
                and isinstance(incoming, int)
                and not isinstance(incoming, bool)
                and isinstance(previous, int)
                and not isinstance(previous, bool)
            ):
                merged[field] = max(0, int(current or 0) + incoming - previous)
            elif field in DynamoUserSupport._HISTORY_LIMITS and isinstance(incoming, list):
                combined = list(current) if isinstance(current, list) else []
                known = {json.dumps(item, sort_keys=True, default=str) for item in combined}
                for item in incoming:
                    key = json.dumps(item, sort_keys=True, default=str)
                    if key not in known:
                        combined.append(deepcopy(item))
                        known.add(key)
                merged[field] = combined[-DynamoUserSupport._HISTORY_LIMITS[field] :]
            elif field == "activePlayback" and not incoming_playback_is_newer:
                continue
            elif (
                field == "lastOffsetMs"
                and "activePlayback" in changed_fields
                and not incoming_playback_is_newer
            ):
                continue
            else:
                merged[field] = incoming
        return merged


class InvalidPersistenceKey(ValueError):
    pass


class PersistenceItemTooLarge(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DynamoUserOptions:
    table_name: str
    partition_key_name: str = "id"
    attributes_name: str = "attributes"
    region: str | None = None
    ttl_attribute: str = "expiresAt"
    ttl_days: int | None = None
    conditional_writes: bool = True


class DynamoDbPersistenceAdapter:
    def __init__(self, options: DynamoUserOptions) -> None:
        if not options.table_name:
            raise ValueError("DynamoDbPersistenceAdapter: table_name is required")
        self.table_name = options.table_name
        self.partition_key_name = options.partition_key_name
        self.attributes_name = options.attributes_name
        self.ttl_attribute = options.ttl_attribute
        self.ttl_days = options.ttl_days or settings.HEAR_PERSISTENCE_TTL_DAYS
        self.conditional_writes = options.conditional_writes
        self._table = DynamoTable(
            table_name=options.table_name,
            partition_key=options.partition_key_name,
            region=options.region or settings.ddb_region,
        )

    def _user_id(self, request_envelope: dict) -> str:
        user_id = User.persistence_key(request_envelope)
        if DynamoUserSupport._is_invalid_key(user_id):
            raise InvalidPersistenceKey(f"invalid persistence key {user_id!r}")
        return user_id

    async def get_attributes(self, request_envelope: dict) -> dict:
        user_id = self._user_id(request_envelope)
        item = await self._table.get_item(user_id)
        if not item:
            return {}
        attributes = item.get(self.attributes_name) or {}
        if not isinstance(attributes, dict):
            attributes = {}
        attributes[DynamoUserSupport._VERSION_FIELD] = int(item.get("stateVersion") or 0)
        return attributes

    @staticmethod
    def _payload(attributes: dict) -> tuple[dict, int, list[str], dict]:
        requested = dict(attributes or {})
        version = max(0, int(requested.pop(DynamoUserSupport._VERSION_FIELD, 0) or 0))
        changed_fields = [
            field
            for field in requested.pop(DynamoUserSupport._CHANGED_FIELDS, [])
            if field in requested
        ]
        original = requested.pop(DynamoUserSupport._ORIGINAL_FIELDS, {})
        return (
            requested,
            version,
            changed_fields or list(requested),
            original if isinstance(original, dict) else {},
        )

    def _validate_document(self, document: dict) -> None:
        size = DynamoExpressions.item_bytes(DynamoExpressions.encode_value(document))
        if size > settings.HEAR_DDB_ITEM_SIZE_MAX_BYTES:
            raise PersistenceItemTooLarge(f"DynamoDB state item is {size} bytes")
        if size > settings.HEAR_DDB_ITEM_SIZE_WARN_BYTES:
            DynamoUserSupport.logger.warning(
                "DynamoDB state item oversized bytes=%s table=%s", size, self.table_name
            )

    def _condition(self, version: int) -> list[dict] | None:
        if not self.conditional_writes:
            return None
        if version == 0:
            return [DynamoExpressions.not_exists("stateVersion")]
        return [DynamoExpressions.eq("stateVersion", version)]

    async def _write(self, operation: dict) -> None:
        version = operation["version"]
        top_level = {
            self.ttl_attribute: operation["expiresAt"],
            "stateVersion": version + 1,
        }
        condition = self._condition(version)
        if self.conditional_writes and version > 0:
            changed = {
                field: operation["document"].get(field) for field in operation["changedFields"]
            }
            await self._table.update_map_fields(
                operation["userId"],
                self.attributes_name,
                changed,
                updates=top_level,
                condition=condition,
            )
            return
        await self._table.update_item(
            operation["userId"],
            updates={self.attributes_name: operation["document"], **top_level},
            condition=condition,
        )

    async def _merge_after_conflict(
        self, request_envelope: dict, operation: dict, attempt: int
    ) -> None:
        DynamoUserSupport.logger.warning(
            "DynamoDB persistence conflict table=%s retry=%s",
            self.table_name,
            attempt + 1,
        )
        latest = await self.get_attributes(request_envelope)
        operation["version"] = max(0, int(latest.pop(DynamoUserSupport._VERSION_FIELD, 0) or 0))
        operation["document"] = DynamoUserSupport.merge_conflict(
            latest,
            operation["requested"],
            operation["original"],
            operation["changedFields"],
        )
        backoff_ms = max(0, settings.HEAR_PERSISTENCE_CONFLICT_BACKOFF_MS) * 2**attempt
        if backoff_ms:
            await asyncio.sleep(backoff_ms / 1000.0)

    async def save_attributes(self, request_envelope: dict, attributes: dict) -> None:
        requested, version, changed_fields, original = self._payload(attributes)
        operation = {
            "userId": self._user_id(request_envelope),
            "expiresAt": int(time.time()) + (self.ttl_days or 180) * 86400,
            "requested": requested,
            "document": dict(requested),
            "version": version,
            "changedFields": changed_fields,
            "original": original,
        }
        retries = (
            max(0, settings.HEAR_PERSISTENCE_CONFLICT_RETRIES) if self.conditional_writes else 0
        )
        for attempt in range(retries + 1):
            self._validate_document(operation["document"])
            try:
                await self._write(operation)
                return
            except ClientError as error:
                if not DynamoUserSupport.is_conditional_failure(error) or attempt >= retries:
                    raise
                await self._merge_after_conflict(request_envelope, operation, attempt)

    async def delete_attributes(self, request_envelope: dict) -> None:
        user_id = self._user_id(request_envelope)
        await self._table.delete_item(user_id)
