from __future__ import annotations

import logging
import time
import uuid
from enum import StrEnum

from config import settings
from src.alexa.request import AlexaRequest
from src.constants.playback import PlaybackConstants
from src.models.user import User
from src.utils.content_normalizer import ContentNormalizer
from src.utils.deadline import DeadlineBudget
from src.utils.filters import SearchFilters
from src.utils.playback import PlaybackUtils


class PlaybackStatus(StrEnum):
    STARTING = "starting"
    PLAYING = "playing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class PlaybackState:
    __slots__ = ("_user",)

    def __init__(self, store: User) -> None:
        self._user = store

    @staticmethod
    def from_store(store: dict) -> dict | None:
        state = store.get("activePlayback") if isinstance(store, dict) else None
        if not isinstance(state, dict) or not state.get("contentId"):
            return None
        return dict(state)

    def current(self, handler_input) -> dict | None:
        return self.from_store(self._user.snapshot(handler_input))

    def start(
        self,
        handler_input,
        content: dict,
        **options,
    ) -> dict:
        alexa_user_id = options.get("alexa_user_id")
        queue_id = options.get("queue_id")
        queue_index = options.get("queue_index", 0)
        offset_ms = options.get("offset_ms", 0)
        now = int(time.time() * 1000)
        event_timestamp = AlexaRequest.get_request_timestamp_ms(handler_input) or now
        content_id = content["contentId"]
        state = {
            "alexaUserId": alexa_user_id,
            "contentId": content_id,
            "token": content_id,
            "title": content.get("spokenTitle")
            or content.get("displayTitle")
            or content.get("title"),
            "creatorId": content.get("creatorId"),
            "creatorName": content.get("creatorName") or content.get("creator"),
            "organizationId": content.get("organizationId"),
            "organizationName": content.get("organizationName"),
            "publicationId": content.get("publicationId"),
            "publicationTitle": content.get("publicationTitle"),
            "isPublication": bool(content.get("isPublication")),
            "trackIndex": content.get("trackIndex"),
            "trackCount": content.get("trackCount"),
            "category": content.get("category"),
            "queueId": queue_id,
            "queueIndex": max(0, int(queue_index or 0)),
            "audioUrl": content.get("audioUrl"),
            "durationMs": content.get("durationMs"),
            "offsetMs": max(0, int(offset_ms or 0)),
            "listenedMs": 0,
            "sessionId": f"{content_id}:{uuid.uuid4().hex}",
            "status": PlaybackStatus.STARTING.value,
            "startedAt": now,
            "updatedAt": now,
            "eventTimestamp": event_timestamp,
        }
        self._user.update(handler_input, {"activePlayback": state})
        return state

    def merge(self, handler_input, changes: dict) -> dict | None:
        if not isinstance(changes, dict):
            return None
        current = self.current(handler_input) or {}
        if not self.accepts_event(handler_input, current):
            return current or None
        now = int(time.time() * 1000)
        request_type = AlexaRequest.get_request_type(handler_input)
        event_timestamp = AlexaRequest.get_request_timestamp_ms(handler_input) or now
        request_id = AlexaRequest.get_request_id(handler_input)
        event_fields = (
            {"eventTimestamp": event_timestamp, "lastEventRequestId": request_id}
            if request_type.startswith("AudioPlayer.")
            else {}
        )
        merged = {**current, **changes, **event_fields, "updatedAt": now}
        if not merged.get("contentId"):
            return None
        merged["token"] = merged["contentId"]
        self._user.update(handler_input, {"activePlayback": merged})
        return merged

    @staticmethod
    def accepts_event(handler_input, current: dict | None = None) -> bool:
        request_type = AlexaRequest.get_request_type(handler_input)
        if not request_type.startswith("AudioPlayer."):
            return True
        state = current if isinstance(current, dict) else {}
        request_id = AlexaRequest.get_request_id(handler_input)
        if request_id and request_id == state.get("lastEventRequestId"):
            return False
        event_timestamp = AlexaRequest.get_request_timestamp_ms(handler_input)
        current_timestamp = int(state.get("eventTimestamp") or 0)
        return event_timestamp is None or event_timestamp >= current_timestamp

    def transition(
        self,
        handler_input,
        status: PlaybackStatus | str,
        *,
        offset_ms: int | None = None,
        listened_ms: int | None = None,
    ) -> dict | None:
        changes = {"status": str(status)}
        if isinstance(status, PlaybackStatus):
            changes["status"] = status.value
        if offset_ms is not None:
            changes["offsetMs"] = max(0, int(offset_ms))
        if listened_ms is not None:
            changes["listenedMs"] = max(0, int(listened_ms))
        return self.merge(handler_input, changes)

    def has_unfinished(self, store: dict) -> bool:
        state = self.from_store(store)
        if not state or state.get("status") not in PlaybackConstants.ACTIVE_PLAYBACK_STATUSES:
            return False
        audio_url = state.get("audioUrl") or store.get("currentAudioUrl")
        return isinstance(audio_url, str) and audio_url.strip().lower().startswith("https://")

    def prepare_next(self, handler_input, content: dict) -> dict:
        return self._user.update(handler_input, {"preparedNextContent": content})

    def clear_prepared(self, handler_input) -> dict:
        return self._user.update(handler_input, {"preparedNextContent": None})

    def prepared(self, store: dict) -> dict | None:
        content = store.get("preparedNextContent") if isinstance(store, dict) else None
        return dict(content) if isinstance(content, dict) else None

    def set_speed(self, handler_input, speed: float) -> dict:
        return self._user.update(handler_input, {"playbackSpeed": speed})

    def save_position(self, handler_input, token: str, offset_ms: int) -> dict:
        return self._user.update(
            handler_input, {"lastToken": token, "lastOffsetMs": max(0, int(offset_ms))}
        )

    def save_current_content(
        self,
        handler_input,
        content: dict,
        *,
        title: str,
        creator: str | None,
        offset_ms: int,
    ) -> dict:
        duration = content.get("durationMs")
        store = self._user.snapshot(handler_input)
        return self._user.update(
            handler_input,
            {
                "playCount": store.get("playCount", 0) + 1,
                "lastToken": content["contentId"],
                "lastOffsetMs": max(0, int(offset_ms or 0)),
                "currentContentId": content["contentId"],
                "currentContentTitle": title,
                "currentCreator": creator,
                "currentCreatorId": content.get("creatorId"),
                "currentOrganization": content.get("organizationName"),
                "currentOrganizationId": content.get("organizationId"),
                "currentPublicationId": content.get("publicationId"),
                "currentTrackIndex": content.get("trackIndex"),
                "currentTotalTracks": content.get("trackCount"),
                "currentCategory": content.get("category"),
                "currentDurationSecs": duration / 1000
                if isinstance(duration, (int, float))
                else None,
                "currentPlaybackSpeeds": content.get("playbackSpeeds") or [],
                "currentAudioUrl": content["audioUrl"],
            },
        )

    def save_resumed_content(
        self,
        handler_input,
        *,
        content_id: str,
        title: str | None,
        audio_url: str,
        offset_ms: int,
    ) -> dict:
        return self._user.update(
            handler_input,
            {
                "lastToken": content_id,
                "lastOffsetMs": max(0, int(offset_ms)),
                "currentContentId": content_id,
                "currentContentTitle": title,
                "currentAudioUrl": audio_url,
            },
        )

    def save_audio_url(self, handler_input, audio_url: str) -> dict:
        return self._user.update(handler_input, {"currentAudioUrl": audio_url})

    def save_completed_source(self, handler_input, source: dict) -> dict:
        return self._user.update(handler_input, {"lastCompletedSource": source})


class PlaybackQueue:
    logger = logging.getLogger(__name__)
    __slots__ = ("_user",)

    def __init__(self, store: User) -> None:
        self._user = store

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

    def move(self, handler_input, delta: int) -> str | None:
        queue = self.read(self._user.snapshot(handler_input))
        if not queue:
            return None
        target = int(queue.get("currentIndex", 0)) + delta
        content_id = self.content_id({"playbackQueue": queue}, target)
        if not content_id:
            return None
        queue["currentIndex"] = target
        self._user.update(handler_input, {"playbackQueue": queue})
        return content_id

    def set_index_for_content(self, handler_input, content_id: str) -> int | None:
        queue = self.read(self._user.snapshot(handler_input))
        if not queue or content_id not in queue["orderedContentIds"]:
            return None
        index = queue["orderedContentIds"].index(content_id)
        queue["currentIndex"] = index
        self._user.update(handler_input, {"playbackQueue": queue})
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
                    and ContentNormalizer.is_playable_content_item(item)
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
            n = PlaybackUtils.normalize_history_entry(entry)
            if n:
                push(n["id"])
            if len(out) >= cap:
                return out[:cap]
        return out[:cap]

    @staticmethod
    def recent_exclude_filters(store: dict, limit: int | None = None) -> dict:
        return SearchFilters.content_ids(PlaybackQueue.recent_content_ids(store, limit))

    def initialize(
        self,
        handler_input,
        items: list,
        **options,
    ) -> dict:
        source = options.get("source")
        start_index = options.get("start_index", 0)
        search_payload = options.get("search_payload")
        current_page = options.get("current_page")
        total_pages = options.get("total_pages")
        page_limit = options.get("page_limit")
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
            item for item in items or [] if isinstance(item, dict) and item.get("publicationId")
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
                and all((isinstance(value, (int, float)) and value > 0 for value in durations))
            ):
                publication_total_duration_ms = sum((int(value) for value in durations))
        queue = {
            "queueId": uuid.uuid4().hex,
            "source": source or "search",
            "publicationId": next(iter(publication_ids)) if len(publication_ids) == 1 else None,
            "publicationTitle": next(iter(publication_titles))
            if len(publication_titles) == 1
            else None,
            "publicationTrackCount": publication_track_count,
            "publicationTotalDurationMs": publication_total_duration_ms,
            "orderedContentIds": content_ids,
            "currentIndex": max(0, min(int(start_index or 0), max(len(content_ids) - 1, 0))),
            "createdAt": int(time.time() * 1000),
        }
        if (
            isinstance(search_payload, dict)
            and isinstance(total_pages, (int, float))
            and (int(total_pages) > int(current_page or 0) + 1)
        ):
            queue["pagination"] = {
                "searchPayload": dict(search_payload),
                "currentPage": int(current_page or 0),
                "totalPages": int(total_pages),
                "limit": int(
                    page_limit or search_payload.get("limit") or settings.search_page_limit
                ),
            }
        return self._user.update(handler_input, {"playbackQueue": queue})

    def clear(self, handler_input) -> dict:
        return self._user.update(handler_input, {"playbackQueue": None})

    def reset_completed(self, handler_input) -> dict:
        return self._user.update(handler_input, {"queueItemsCompleted": 0})

    def save_loaded_page(self, handler_input, queue: dict, browse_catalog: dict | None) -> dict:
        return self._user.update(
            handler_input, {"playbackQueue": queue, "browseCatalog": browse_catalog}
        )

    @staticmethod
    def _page_request(handler_input, pagination: dict) -> tuple[dict, int]:
        next_page = int(pagination.get("currentPage") or 0) + 1
        payload = dict(pagination.get("searchPayload") or {})
        payload.update(
            {
                "page": next_page,
                "limit": int(pagination.get("limit") or payload.get("limit") or 3),
            }
        )
        user_id = AlexaRequest.get_user_id(handler_input)
        if user_id:
            payload["alexaUserId"] = user_id
        return payload, next_page

    @staticmethod
    def _merge_page(queue: dict, pagination: dict, result: dict, next_page: int) -> int:
        content_ids = list(queue["orderedContentIds"])
        previous_count = len(content_ids)
        seen = set(content_ids)
        for item in result.get("results") or []:
            content_id = item.get("contentId") or item.get("id") if isinstance(item, dict) else None
            if content_id and str(content_id) not in seen:
                seen.add(str(content_id))
                content_ids.append(str(content_id))
        queue["orderedContentIds"] = content_ids
        pagination["currentPage"] = int(result.get("page") or next_page)
        if isinstance(result.get("total_pages"), (int, float)):
            pagination["totalPages"] = int(result["total_pages"])
        queue["pagination"] = pagination
        return len(content_ids) - previous_count

    @staticmethod
    def _merge_catalog(catalog: dict, page_items: list[dict]) -> dict | None:
        if not catalog:
            return None
        items = list(catalog.get("items") or [])
        cached_ids = {
            str(item.get("contentId") or item.get("id"))
            for item in items
            if isinstance(item, dict) and (item.get("contentId") or item.get("id"))
        }
        for item in page_items:
            content_id = item.get("contentId") or item.get("id")
            if (
                content_id
                and str(content_id) not in cached_ids
                and ContentNormalizer.is_playable_content_item(item)
            ):
                cached_ids.add(str(content_id))
                items.append(item)
        limit = max(1, int(settings.HEAR_BROWSE_MAX_CATALOG or 50))
        catalog.update({"items": items[-limit:], "currentPage": catalog.get("currentPage", 0) + 1})
        return catalog

    async def load_next_page(self, handler_input, hear_client) -> bool:
        queue = self.read(self._user.snapshot(handler_input))
        pagination = queue.get("pagination") if queue else None
        if not queue or not isinstance(pagination, dict):
            return False
        current_page = int(pagination.get("currentPage") or 0)
        total_pages = int(pagination.get("totalPages") or 0)
        if total_pages <= 0 or current_page + 1 >= total_pages:
            return False
        payload, next_page = PlaybackQueue._page_request(handler_input, pagination)
        result = await hear_client.search(
            payload, timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input)
        )
        if result.get("failed"):
            PlaybackQueue.logger.warning(
                "Hear: lazy queue page failed page=%s totalPages=%s", next_page, total_pages
            )
            return False
        page_items = [item for item in result.get("results") or [] if isinstance(item, dict)]
        added = PlaybackQueue._merge_page(queue, pagination, result, next_page)
        catalog = PlaybackQueue._merge_catalog(
            dict(self._user.snapshot(handler_input).get("browseCatalog") or {}), page_items
        )
        self.save_loaded_page(handler_input, queue, catalog)
        return added > 0
