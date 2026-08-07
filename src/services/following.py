from __future__ import annotations
from src.services.store import get_store, update_store


class FollowingManager:
    __slots__ = ()

    @staticmethod
    def add(handler_input, creator_id: str, creator_name: str) -> dict:
        store = get_store(handler_input)
        followed = list(store.get("followedCreators") or [])
        if any(c.get("id") == creator_id for c in followed):
            return store
        followed.append({"id": creator_id, "name": creator_name})
        return update_store(handler_input, {"followedCreators": followed})

    @staticmethod
    def remove(handler_input, creator_id: str) -> dict:
        store = get_store(handler_input)
        followed = [c for c in (store.get("followedCreators") or []) if c.get("id") != creator_id]
        return update_store(handler_input, {"followedCreators": followed})

    @staticmethod
    def is_following(store: dict, creator_id: str) -> bool:
        return any(c.get("id") == creator_id for c in (store.get("followedCreators") or []))


_following = FollowingManager()
add_followed_creator = _following.add
remove_followed_creator = _following.remove
is_following = _following.is_following
