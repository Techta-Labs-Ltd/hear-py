from __future__ import annotations

from src.constants.state import StateSchema
from src.models.user import User


class MemoryPersistenceAdapter:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    async def get_attributes(
        self, request_envelope: dict, *, persistence_key: str | None = None
    ) -> dict:
        user_id = persistence_key or User.persistence_key(request_envelope)
        raw = self._store.get(user_id)
        return dict(raw) if isinstance(raw, dict) else {}

    async def save_attributes(
        self,
        request_envelope: dict,
        attributes: dict,
        *,
        persistence_key: str | None = None,
    ) -> None:
        user_id = persistence_key or User.persistence_key(request_envelope)
        document = dict(attributes)
        versions = document.pop("_persistenceVersions", {})
        if not isinstance(versions, dict):
            versions = {}
        changed = document.pop("_persistenceChangedFields", None)
        changed_fields = (
            list(changed)
            if isinstance(changed, (list, tuple, set))
            else list(document)
        )
        document.pop("_persistenceOriginal", None)
        changed_scopes = {
            scope
            for field in changed_fields
            if (scope := StateSchema.scope_for(field)) is not None
        }
        for scope in changed_scopes:
            versions[scope] = max(0, int(versions.get(scope) or 0)) + 1
        document["_persistenceVersions"] = versions
        self._store[user_id] = document

    async def delete_attributes(
        self, request_envelope: dict, *, persistence_key: str | None = None
    ) -> None:
        user_id = persistence_key or User.persistence_key(request_envelope)
        self._store.pop(user_id, None)
