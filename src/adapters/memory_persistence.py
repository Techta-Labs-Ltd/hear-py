from .persistence_user_id import resolve_persistence_user_id


class MemoryPersistenceAdapter:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    async def get_attributes(self, request_envelope: dict) -> dict:
        user_id = resolve_persistence_user_id(request_envelope)
        raw = self._store.get(user_id)
        return dict(raw) if isinstance(raw, dict) else {}

    async def save_attributes(self, request_envelope: dict, attributes: dict) -> None:
        user_id = resolve_persistence_user_id(request_envelope)
        self._store[user_id] = dict(attributes)

    async def delete_attributes(self, request_envelope: dict) -> None:
        user_id = resolve_persistence_user_id(request_envelope)
        self._store.pop(user_id, None)
