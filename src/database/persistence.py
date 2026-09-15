from __future__ import annotations

from copy import deepcopy

from src.constants.state import StateSchema
from src.database.dynamo_merge import DynamoConflictMerge
from src.models.user import PersistenceReceipt, User


class MemoryPersistenceAdapter:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    async def get_attributes(
        self, request_envelope: dict, *, persistence_key: str | None = None
    ) -> dict:
        user_id = persistence_key or User.persistence_key(request_envelope)
        raw = self._store.get(user_id)
        return deepcopy(raw) if isinstance(raw, dict) else {}

    async def save_attributes(
        self,
        request_envelope: dict,
        attributes: dict,
        *,
        persistence_key: str | None = None,
    ) -> PersistenceReceipt:
        user_id = persistence_key or User.persistence_key(request_envelope)
        document = deepcopy(attributes)
        versions = document.pop("_persistenceVersions", {})
        if not isinstance(versions, dict):
            versions = {}
        changed = document.pop("_persistenceChangedFields", None)
        changed_fields = (
            list(changed) if isinstance(changed, (list, tuple, set)) else list(document)
        )
        original = document.pop("_persistenceOriginal", {})
        for field in StateSchema.LEGACY_DATABASE_FIELDS:
            document.pop(field, None)
        latest = deepcopy(self._store.get(user_id) or {})
        for field in StateSchema.LEGACY_DATABASE_FIELDS:
            latest.pop(field, None)
        current_versions = latest.pop("_persistenceVersions", {})
        changed_scopes = {
            scope for field in changed_fields if (scope := StateSchema.scope_for(field)) is not None
        }
        if any(
            current_versions.get(scope, 0) != versions.get(scope, 0) for scope in changed_scopes
        ):
            document = DynamoConflictMerge.resolve(latest, document, original, changed_fields)
        else:
            for field in changed_fields:
                if field in document:
                    latest[field] = deepcopy(document[field])
                else:
                    latest.pop(field, None)
            document = latest
        for scope in changed_scopes:
            current_versions[scope] = max(0, int(current_versions.get(scope) or 0)) + 1
        self._store[user_id] = {
            **deepcopy(document),
            "_persistenceVersions": dict(current_versions),
        }
        return PersistenceReceipt(versions=dict(current_versions), snapshot=deepcopy(document))

    async def delete_attributes(
        self, request_envelope: dict, *, persistence_key: str | None = None
    ) -> None:
        user_id = persistence_key or User.persistence_key(request_envelope)
        self._store.pop(user_id, None)
