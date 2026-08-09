from __future__ import annotations
from src.services.store import get_store, update_store


class FollowingManager:
    __slots__ = ()

    @staticmethod
    def add(handler_input, source_id: str, source_name: str, source_type: str = "creator") -> dict:
        store = get_store(handler_input)
        followed = list(store.get("followedCreators") or [])
        source_type = "organization" if source_type == "organization" else "creator"
        if any(c.get("id") == source_id and c.get("type", "creator") == source_type for c in followed):
            return store
        followed.append({"id": source_id, "name": source_name, "type": source_type})
        return update_store(handler_input, {"followedCreators": followed})

    @staticmethod
    def remove(handler_input, source_id: str, source_type: str = "creator") -> dict:
        store = get_store(handler_input)
        followed = [
            c for c in (store.get("followedCreators") or [])
            if not (c.get("id") == source_id and c.get("type", "creator") == source_type)
        ]
        return update_store(handler_input, {"followedCreators": followed})

    @staticmethod
    def is_following(store: dict, source_id: str, source_type: str = "creator") -> bool:
        return any(
            c.get("id") == source_id and c.get("type", "creator") == source_type
            for c in (store.get("followedCreators") or [])
        )


_following = FollowingManager()
add_followed_creator = _following.add
remove_followed_creator = _following.remove
is_following = _following.is_following
