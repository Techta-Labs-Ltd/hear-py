from __future__ import annotations
from src.services.store import get_store, update_store
def add_followed_creator(handler_input, creator_id: str, creator_name: str) -> dict:
    """Add a creator to the user's followed list (idempotent)."""
    store = get_store(handler_input)
    followed = list(store.get("followedCreators") or [])
    if any(c.get("id") == creator_id for c in followed):
        return store
    followed.append({"id": creator_id, "name": creator_name})
    return update_store(handler_input, {"followedCreators": followed})


def remove_followed_creator(handler_input, creator_id: str) -> dict:
    """Remove a creator from the user's followed list."""
    store = get_store(handler_input)
    followed = [c for c in (store.get("followedCreators") or []) if c.get("id") != creator_id]
    return update_store(handler_input, {"followedCreators": followed})


def is_following(store: dict, creator_id: str) -> bool:
    """Return True if *creator_id* is in the user's followed list."""
    return any(c.get("id") == creator_id for c in (store.get("followedCreators") or []))
