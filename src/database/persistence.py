from __future__ import annotations

from src.models.user import User


class MemoryPersistenceAdapter:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    async def get_attributes(self, request_envelope: dict) -> dict:
        user_id = User.persistence_key(request_envelope)
        raw = self._store.get(user_id)
        return dict(raw) if isinstance(raw, dict) else {}

    async def save_attributes(self, request_envelope: dict, attributes: dict) -> None:
        user_id = User.persistence_key(request_envelope)
        document = dict(attributes)
        version = max(0, int(document.pop("_persistenceVersion", 0) or 0))
        document.pop("_persistenceChangedFields", None)
        document.pop("_persistenceOriginal", None)
        document["_persistenceVersion"] = version + 1
        self._store[user_id] = document

    async def delete_attributes(self, request_envelope: dict) -> None:
        user_id = User.persistence_key(request_envelope)
        self._store.pop(user_id, None)
