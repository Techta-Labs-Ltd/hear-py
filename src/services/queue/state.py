from __future__ import annotations

import time
import uuid

from src.services.storage.persistence import get_store, update_store
from src.utils.normalize_content_item import is_playable_content_item
from src.utils.session_queue import clone_queue_item


def read_playback_queue(store: dict) -> dict | None:
    queue = store.get("playbackQueue") if isinstance(store, dict) else None
    if not isinstance(queue, dict):
        return None
    ids = queue.get("orderedContentIds")
    if not isinstance(ids, list) or not ids:
        return None
    return dict(queue)


def create_playback_queue(
    handler_input,
    content_ids: list[str],
    *,
    source: str,
    publication_id: str | None = None,
    publication_title: str | None = None,
) -> dict:
    ordered = list(dict.fromkeys(str(value) for value in content_ids if value))
    queue = {
        "queueId": uuid.uuid4().hex,
        "source": source,
        "publicationId": publication_id,
        "publicationTitle": publication_title,
        "orderedContentIds": ordered,
        "currentIndex": 0,
        "createdAt": int(time.time() * 1000),
    }
    update_store(handler_input, {"playbackQueue": queue})
    return queue


def cache_queue_content_items(handler_input, items: list[dict]) -> list[dict]:
    cached = [
        clone_queue_item(item)
        for item in items or []
        if is_playable_content_item(item)
    ]
    cached = [item for item in cached if item]
    update_store(handler_input, {"browseQueueItems": cached or None})
    return cached


def queue_content_id(store: dict, index: int | None = None) -> str | None:
    queue = read_playback_queue(store)
    if not queue:
        return None
    target = queue.get("currentIndex", 0) if index is None else index
    ids = queue["orderedContentIds"]
    return ids[target] if isinstance(target, int) and 0 <= target < len(ids) else None


def move_queue(handler_input, delta: int) -> str | None:
    queue = read_playback_queue(get_store(handler_input))
    if not queue:
        return None
    target = int(queue.get("currentIndex", 0)) + delta
    content_id = queue_content_id({"playbackQueue": queue}, target)
    if not content_id:
        return None
    queue["currentIndex"] = target
    update_store(handler_input, {"playbackQueue": queue})
    return content_id


def set_queue_index_for_content(handler_input, content_id: str) -> int | None:
    queue = read_playback_queue(get_store(handler_input))
    if not queue or content_id not in queue["orderedContentIds"]:
        return None
    index = queue["orderedContentIds"].index(content_id)
    queue["currentIndex"] = index
    update_store(handler_input, {"playbackQueue": queue})
    return index


def clear_playback_queue(handler_input) -> None:
    update_store(handler_input, {"playbackQueue": None})


def cached_queue_content(store: dict, content_id: str) -> dict | None:
    """Resolve a queued item from the persisted search catalog without I/O."""
    if not isinstance(store, dict) or not content_id:
        return None
    sources = [
        (store.get("browseCatalog") or {}).get("items"),
        store.get("pendingBrowseItems"),
        store.get("browseQueueItems"),
    ]
    for items in sources:
        if not isinstance(items, list):
            continue
        for item in items:
            if (
                isinstance(item, dict)
                and item.get("contentId") == content_id
                and is_playable_content_item(item)
            ):
                return dict(item)
    return None
