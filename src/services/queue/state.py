from __future__ import annotations

import time
import uuid

from src.services.storage.persistence import get_store, update_store


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
