from __future__ import annotations
import time
import uuid
from src.services.store import get_store, update_store
from src.utils.normalize_content_item import is_playable_content_item
from config import settings
from src.services.persistence import _normalize_play_history_entry


class PlaybackQueue:
    __slots__ = ()

    @staticmethod
    def read(store: dict) -> dict | None:
        queue = store.get("playbackQueue") if isinstance(store, dict) else None
        if not isinstance(queue, dict):
            return None
        ids = queue.get("orderedContentIds")
        if not isinstance(ids, list) or not ids:
            return None
        return dict(queue)

    @staticmethod
    def content_id(store: dict, index: int | None = None) -> str | None:
        queue = PlaybackQueue.read(store)
        if not queue:
            return None
        target = queue.get("currentIndex", 0) if index is None else index
        ids = queue["orderedContentIds"]
        return ids[target] if isinstance(target, int) and 0 <= target < len(ids) else None

    @staticmethod
    def move(handler_input, delta: int) -> str | None:
        queue = PlaybackQueue.read(get_store(handler_input))
        if not queue:
            return None
        target = int(queue.get("currentIndex", 0)) + delta
        content_id = PlaybackQueue.content_id({"playbackQueue": queue}, target)
        if not content_id:
            return None
        queue["currentIndex"] = target
        update_store(handler_input, {"playbackQueue": queue})
        return content_id

    @staticmethod
    def set_index_for_content(handler_input, content_id: str) -> int | None:
        queue = PlaybackQueue.read(get_store(handler_input))
        if not queue or content_id not in queue["orderedContentIds"]:
            return None
        index = queue["orderedContentIds"].index(content_id)
        queue["currentIndex"] = index
        update_store(handler_input, {"playbackQueue": queue})
        return index

    @staticmethod
    def cached_content(store: dict, content_id: str) -> dict | None:
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

    @staticmethod
    def recent_content_ids(store: dict, limit: int | None = None) -> list:
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

    @staticmethod
    def recent_exclude_filters(store: dict, limit: int | None = None) -> dict:
        return {"contentIds": PlaybackQueue.recent_content_ids(store, limit)}

    @staticmethod
    def init(
        handler_input,
        items: list,
        *,
        source: str | None = None,
        locality: str | None = None,
        category: str | None = None,
        start_index: int = 0,
        search_payload: dict | None = None,
        current_page: int | None = None,
        total_pages: int | None = None,
        page_limit: int | None = None,
    ) -> dict:
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
        publication_items = [
            item for item in items or []
            if isinstance(item, dict) and item.get("publicationId")
        ]
        publication_track_count = None
        publication_total_duration_ms = None
        if len(publication_ids) == 1:
            declared_counts = []
            for item in publication_items:
                try:
                    declared = int(item.get("trackCount") or 0)
                except (TypeError, ValueError):
                    declared = 0
                if declared > 0:
                    declared_counts.append(declared)
            publication_track_count = max(declared_counts, default=len(publication_items))
            durations = [item.get("durationMs") for item in publication_items]
            if (
                publication_track_count == len(publication_items)
                and durations
                and all(isinstance(value, (int, float)) and value > 0 for value in durations)
            ):
                publication_total_duration_ms = sum(int(value) for value in durations)
        queue = {
            "queueId": uuid.uuid4().hex,
            "source": source or "search",
            "publicationId": next(iter(publication_ids)) if len(publication_ids) == 1 else None,
            "publicationTitle": next(iter(publication_titles)) if len(publication_titles) == 1 else None,
            "publicationTrackCount": publication_track_count,
            "publicationTotalDurationMs": publication_total_duration_ms,
            "orderedContentIds": content_ids,
            "currentIndex": max(0, min(int(start_index or 0), max(len(content_ids) - 1, 0))),
            "createdAt": int(time.time() * 1000),
        }
        if (
            isinstance(search_payload, dict)
            and isinstance(total_pages, (int, float))
            and int(total_pages) > int(current_page or 0) + 1
        ):
            queue["pagination"] = {
                "searchPayload": dict(search_payload),
                "currentPage": int(current_page or 0),
                "totalPages": int(total_pages),
                "limit": int(page_limit or search_payload.get("limit") or settings.search_page_limit),
            }
        return update_store(handler_input, {"playbackQueue": queue})

    @staticmethod
    def clear(handler_input) -> dict:
        return update_store(handler_input, {"playbackQueue": None})

    @staticmethod
    def reset_completed(handler_input) -> dict:
        return update_store(handler_input, {"queueItemsCompleted": 0})


# module-level aliases for backward compatibility
_playback_queue = PlaybackQueue()
read_playback_queue = _playback_queue.read
queue_content_id = _playback_queue.content_id
move_queue = _playback_queue.move
set_queue_index_for_content = _playback_queue.set_index_for_content
cached_queue_content = _playback_queue.cached_content
recent_content_ids = _playback_queue.recent_content_ids
recent_exclude_filters = _playback_queue.recent_exclude_filters
init_queue = _playback_queue.init
clear_queue = _playback_queue.clear
reset_queue_items_completed = _playback_queue.reset_completed
