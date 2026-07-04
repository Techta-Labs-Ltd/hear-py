from __future__ import annotations

from src.utils.normalize_content_item import normalize_content_items
from src.services.persistence import add_to_history


def _normalize_play_history_id(entry) -> str | None:
    """Extract a normalized ID from a play history entry."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict) and entry.get("id"):
        return str(entry["id"])
    return None


def build_playback_exclude_set(store: dict | None, *, include_future_queue: bool = True) -> set:
    """Build a set of content IDs to exclude from future playback suggestions."""
    ids: set = set()

    def add(val):
        if val is not None and str(val).strip():
            ids.add(str(val))

    store = store or {}
    add(store.get("lastToken"))
    add(store.get("feedbackContentId"))
    add(store.get("playbackTrackId"))
    add(store.get("currentContentId"))
    add(store.get("playbackParentId"))
    add(store.get("currentPublicationId"))
    add(store.get("lastPlayedCatalogId"))

    for entry in store.get("playHistory") or []:
        add(_normalize_play_history_id(entry))

    queue = store.get("upcomingQueue") or []
    queue_idx = store.get("queueIndex") or 0
    end_idx = len(queue) - 1 if include_future_queue else queue_idx
    for i in range(min(end_idx + 1, len(queue))):
        item = queue[i]
        if isinstance(item, dict):
            add(item.get("id"))

    return ids


def pick_next_search_item(items, exclude_set: set, skip_parent_id=None) -> dict | None:
    """Pick the next content item from a list, respecting the exclude set."""
    lst = [i for i in normalize_content_items(items or []) if isinstance(i, dict) and i.get("id") and str(i["id"]) not in exclude_set]
    for item in lst:
        if skip_parent_id is not None and str(item["id"]) == str(skip_parent_id):
            continue
        if str(item["id"]) not in exclude_set:
            return item
    return None


def record_current_playback_for_skip(handler_input, store: dict):
    """Record the current content as skipped in the playback history."""
    content_id = (
        store.get("playbackParentId")
        or store.get("currentPublicationId")
        or store.get("lastPlayedCatalogId")
        or store.get("currentContentId")
    )
    if not content_id:
        return
    add_to_history(handler_input, content_id, recording_id=store.get("currentRecordingId") or None)
