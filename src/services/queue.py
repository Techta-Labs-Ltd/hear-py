from __future__ import annotations
import time
import uuid
from src.services.store import get_store, update_store
from src.utils.normalize_content_item import is_playable_content_item
from config import settings
from src.services.persistence import _normalize_play_history_entry

def read_playback_queue(store: dict) -> dict | None:
    queue = store.get("playbackQueue") if isinstance(store, dict) else None
    if not isinstance(queue, dict):
        return None
    ids = queue.get("orderedContentIds")
    if not isinstance(ids, list) or not ids:
        return None
    return dict(queue)


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



def recent_content_ids(store: dict, limit: int | None = None) -> list:
    """Compile the list of recently-seen content IDs for exclusion filters."""
    cap = limit or settings.HEAR_RECENT_EXCLUDE_LIMIT or settings.max_history or 20
    seen: set[str] = set()
    out: list[str] = []

    def push(val) -> None:
        k = str(val) if val is not None else None
        if k and k not in seen:
            seen.add(k)
            out.append(k)

    push(store.get("currentContentId"))
    push(store.get("feedbackContentId"))
    active = store.get("activePlayback") or {}
    push(active.get("contentId"))
    push(store.get("lastToken"))
    for entry in store.get("playHistory") or []:
        n = _normalize_play_history_entry(entry)
        if n:
            push(n["id"])
        if len(out) >= cap:
            return out[:cap]
    return out[:cap]


def recent_exclude_filters(store: dict, limit: int | None = None) -> dict:
    """Build an exclusion-filters dict for search queries."""
    return {"contentIds": recent_content_ids(store, limit)}


def init_queue(
    handler_input,
    items: list,
    *,
    source: str | None = None,
    locality: str | None = None,
    category: str | None = None,
    start_index: int = 0,
) -> dict:
    """Initialise the canonical content-ID playback queue."""
    del locality, category
    content_ids = []
    for item in items or []:
        value = item.get("contentId") if isinstance(item, dict) else item
        if value and str(value) not in content_ids:
            content_ids.append(str(value))
    publication_ids = {
        str(item.get("publicationId"))
        for item in items or []
        if isinstance(item, dict) and item.get("publicationId")
    }
    publication_titles = {
        str(item.get("publicationTitle"))
        for item in items or []
        if isinstance(item, dict) and item.get("publicationTitle")
    }
    queue = {
        "queueId": uuid.uuid4().hex,
        "source": source or "search",
        "publicationId": next(iter(publication_ids)) if len(publication_ids) == 1 else None,
        "publicationTitle": next(iter(publication_titles)) if len(publication_titles) == 1 else None,
        "orderedContentIds": content_ids,
        "currentIndex": max(0, min(int(start_index or 0), max(len(content_ids) - 1, 0))),
        "createdAt": int(time.time() * 1000),
    }
    return update_store(handler_input, {"playbackQueue": queue})


def clear_queue(handler_input) -> dict:
    """Empty the queue and reset all queue-related state."""
    return update_store(handler_input, {"playbackQueue": None})


def reset_queue_items_completed(handler_input) -> dict:
    """Reset the completed-queue-items counter to zero."""
    return update_store(handler_input, {"queueItemsCompleted": 0})
