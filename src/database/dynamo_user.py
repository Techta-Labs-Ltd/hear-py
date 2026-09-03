from __future__ import annotations

import asyncio
import logging
import time
from copy import deepcopy
from dataclasses import dataclass

from botocore.exceptions import ClientError

from config import settings
from src.constants.state import StateSchema
from src.database.dynamo_merge import DynamoConflictMerge
from src.database.dynamodb import DynamoExpressions, DynamoTable
from src.models.user import User


class DynamoUserSupport:
    logger = logging.getLogger(__name__)
    _VERSIONS_FIELD = "_persistenceVersions"
    _CHANGED_FIELDS = "_persistenceChangedFields"
    _ORIGINAL_FIELDS = "_persistenceOriginal"
    _CANONICAL_COPY_FIELD = "_persistenceNeedsCanonicalCopy"

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
            sort_key_name=settings.HEAR_DDB_SORT_KEY or "scope",
            ttl_days=settings.HEAR_PERSISTENCE_TTL_DAYS,
            conditional_writes=settings.HEAR_PERSISTENCE_CONDITIONAL,
        )
        return DynamoDbPersistenceAdapter(options)

    @staticmethod
    def is_conditional_failure(error: ClientError) -> bool:
        return error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"

class InvalidPersistenceKey(ValueError):
    pass


class PersistenceItemTooLarge(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DynamoUserOptions:
    table_name: str
    partition_key_name: str = "id"
    sort_key_name: str = "scope"
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
        self.sort_key_name = options.sort_key_name
        self.attributes_name = options.attributes_name
        self.ttl_attribute = options.ttl_attribute
        self.ttl_days = options.ttl_days or settings.HEAR_PERSISTENCE_TTL_DAYS
        self.conditional_writes = options.conditional_writes
        region = options.region or settings.ddb_region
        self._table = DynamoTable(
            table_name=options.table_name,
            partition_key=options.partition_key_name,
            sort_key=options.sort_key_name,
            region=region,
        )

    def _user_id(self, request_envelope: dict, persistence_key: str | None = None) -> str:
        user_id = persistence_key or User.persistence_key(request_envelope)
        if DynamoUserSupport._is_invalid_key(user_id):
            raise InvalidPersistenceKey(f"invalid persistence key {user_id!r}")
        return user_id

    async def _scope_item(self, user_id: str, scope: str) -> dict | None:
        consistent = scope in {StateSchema.PLAYBACK_SCOPE, StateSchema.DIALOG_SCOPE}
        return await self._table.get_item(user_id, scope, consistent=consistent)

    async def get_attributes(
        self, request_envelope: dict, *, persistence_key: str | None = None
    ) -> dict:
        user_id = self._user_id(request_envelope, persistence_key)
        items = await asyncio.gather(
            *(self._scope_item(user_id, scope) for scope in StateSchema.SCOPES)
        )
        if not any(items):
            return {}
        attributes: dict = {}
        versions: dict[str, int] = {}
        for scope, item in zip(StateSchema.SCOPES, items):
            if not isinstance(item, dict):
                versions[scope] = 0
                continue
            document = item.get(self.attributes_name) or {}
            if isinstance(document, dict):
                attributes.update(document)
            versions[scope] = max(0, int(item.get("stateVersion") or 0))
        attributes[DynamoUserSupport._VERSIONS_FIELD] = versions
        return attributes

    @staticmethod
    def _payload(attributes: dict) -> tuple[dict, dict, list[str], dict]:
        requested = dict(attributes or {})
        versions = requested.pop(DynamoUserSupport._VERSIONS_FIELD, {})
        requested.pop(DynamoUserSupport._CANONICAL_COPY_FIELD, None)
        changed = requested.pop(DynamoUserSupport._CHANGED_FIELDS, None)
        changed_fields = (
            [field for field in changed if field in StateSchema.PERSISTED_FIELDS]
            if isinstance(changed, (list, tuple, set))
            else list(requested)
        )
        original = requested.pop(DynamoUserSupport._ORIGINAL_FIELDS, {})
        return (
            requested,
            versions if isinstance(versions, dict) else {},
            changed_fields,
            original if isinstance(original, dict) else {},
        )

    def _validate_document(self, scope: str, document: dict) -> None:
        item = {
            self.partition_key_name: "listener",
            self.sort_key_name: scope,
            self.attributes_name: document,
        }
        size = DynamoExpressions.item_bytes(DynamoExpressions.encode_value(item))
        if size > settings.HEAR_DDB_ITEM_SIZE_MAX_BYTES:
            raise PersistenceItemTooLarge(
                f"DynamoDB {scope} state item is {size} bytes"
            )
        if size > settings.HEAR_DDB_ITEM_SIZE_WARN_BYTES:
            DynamoUserSupport.logger.warning(
                "DynamoDB state item oversized scope=%s bytes=%s table=%s",
                scope,
                size,
                self.table_name,
            )

    def _condition(self, version: int) -> list[dict] | None:
        if not self.conditional_writes:
            return None
        if version == 0:
            return [DynamoExpressions.not_exists("stateVersion")]
        return [DynamoExpressions.eq("stateVersion", version)]

    def _expires_at(self, scope: str, document: dict) -> int:
        now = int(time.time())
        if scope == StateSchema.DIALOG_SCOPE:
            active = document.get("activeDialog") or {}
            active_expiry = int(active.get("expiresAt") or 0) if isinstance(active, dict) else 0
            return max(active_expiry, now + settings.HEAR_DIALOG_STATE_TTL_SECONDS)
        days = {
            StateSchema.CORE_SCOPE: self.ttl_days,
            StateSchema.PLAYBACK_SCOPE: settings.HEAR_PLAYBACK_STATE_TTL_DAYS,
            StateSchema.CACHE_SCOPE: settings.HEAR_LISTENER_CACHE_TTL_DAYS,
        }.get(scope, self.ttl_days)
        return now + max(1, int(days or self.ttl_days)) * 86400

    @staticmethod
    def _scope_document(document: dict, scope: str) -> dict:
        fields = StateSchema.fields_for_scope(scope)
        return {field: deepcopy(document[field]) for field in fields if field in document}

    @staticmethod
    def _scope_values(document: dict, fields: list[str]) -> dict:
        return {
            field: deepcopy(document.get(field, StateSchema.default_for(field)))
            for field in fields
        }

    async def _write(self, operation: dict) -> None:
        version = operation["version"]
        document = operation["document"]
        if version == 0 and not document:
            return
        top_level = {
            self.ttl_attribute: operation["expiresAt"],
            "schemaVersion": StateSchema.SCHEMA_VERSION,
            "stateVersion": version + 1,
        }
        condition = self._condition(version)
        if version == 0:
            await self._table.update_item(
                operation["userId"],
                operation["scope"],
                updates={self.attributes_name: document, **top_level},
                condition=condition,
            )
            return
        changed_values = {
            field: document[field]
            for field in operation["changedFields"]
            if field in document
        }
        removed = [
            field for field in operation["changedFields"] if field not in document
        ]
        await self._table.update_map_fields(
            operation["userId"],
            self.attributes_name,
            changed_values,
            sort_value=operation["scope"],
            removes=removed,
            updates=top_level,
            condition=condition,
        )

    async def _merge_after_conflict(self, operation: dict, attempt: int) -> None:
        DynamoUserSupport.logger.warning(
            "DynamoDB persistence conflict table=%s scope=%s retry=%s",
            self.table_name,
            operation["scope"],
            attempt + 1,
        )
        item = await self._scope_item(operation["userId"], operation["scope"])
        latest = (item or {}).get(self.attributes_name) or {}
        if not isinstance(latest, dict):
            latest = {}
        operation["version"] = max(0, int((item or {}).get("stateVersion") or 0))
        operation["document"] = DynamoConflictMerge.resolve(
            latest,
            operation["requested"],
            operation["original"],
            operation["changedFields"],
        )
        operation["expiresAt"] = self._expires_at(
            operation["scope"], operation["document"]
        )
        backoff_ms = max(0, settings.HEAR_PERSISTENCE_CONFLICT_BACKOFF_MS) * 2**attempt
        if backoff_ms:
            await asyncio.sleep(backoff_ms / 1000.0)

    async def _save_scope(self, operation: dict) -> None:
        retries = (
            max(0, settings.HEAR_PERSISTENCE_CONFLICT_RETRIES)
            if self.conditional_writes
            else 0
        )
        for attempt in range(retries + 1):
            self._validate_document(operation["scope"], operation["document"])
            try:
                await self._write(operation)
                return
            except ClientError as error:
                if not DynamoUserSupport.is_conditional_failure(error) or attempt >= retries:
                    raise
                await self._merge_after_conflict(operation, attempt)

    async def save_attributes(
        self,
        request_envelope: dict,
        attributes: dict,
        *,
        persistence_key: str | None = None,
    ) -> None:
        requested, versions, changed_fields, original = self._payload(attributes)
        user_id = self._user_id(request_envelope, persistence_key)
        operations = []
        for scope in StateSchema.SCOPES:
            scope_fields = [
                field for field in changed_fields if StateSchema.scope_for(field) == scope
            ]
            if not scope_fields:
                continue
            document = self._scope_document(requested, scope)
            operations.append(
                {
                    "userId": user_id,
                    "scope": scope,
                    "expiresAt": self._expires_at(scope, document),
                    "requested": self._scope_values(requested, scope_fields),
                    "document": document,
                    "version": max(0, int(versions.get(scope) or 0)),
                    "changedFields": scope_fields,
                    "original": self._scope_values(original, scope_fields),
                }
            )
        if operations:
            await asyncio.gather(*(self._save_scope(operation) for operation in operations))

    async def delete_attributes(
        self, request_envelope: dict, *, persistence_key: str | None = None
    ) -> None:
        user_id = self._user_id(request_envelope, persistence_key)
        deletes = [self._table.delete_item(user_id, scope) for scope in StateSchema.SCOPES]
        await asyncio.gather(*deletes)
