from __future__ import annotations

from config import settings
from src.constants.state import StateSchema
from src.utils.playback_history import PlaybackHistoryUtils


class UserStateCollections:
    @staticmethod
    def value(value, depth: int = 0):
        if depth >= 8:
            return None
        if isinstance(value, str):
            return value[: max(settings.HEAR_PERSISTED_TEXT_LIMIT, 1)]
        if isinstance(value, list):
            limit = max(settings.HEAR_PERSISTED_COLLECTION_LIMIT, 1)
            return [UserStateCollections.value(item, depth + 1) for item in value[:limit]]
        if isinstance(value, dict):
            limit = max(settings.HEAR_PERSISTED_COLLECTION_LIMIT, 1)
            return {
                str(key): UserStateCollections.value(item, depth + 1)
                for key, item in list(value.items())[:limit]
            }
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[: max(settings.HEAR_PERSISTED_TEXT_LIMIT, 1)]

    @staticmethod
    def feedback_candidates(value) -> list:
        if not isinstance(value, list):
            return []
        allowed = frozenset(
            {
                "category",
                "completed",
                "contentId",
                "contentIds",
                "coverage",
                "createdAt",
                "creatorId",
                "creatorName",
                "discoveryContext",
                "expectedTrackCount",
                "feedbackKey",
                "listenedMs",
                "meaningfulTrackCount",
                "organizationId",
                "organizationName",
                "playbackStartedAt",
                "publicationId",
                "publicationTitle",
                "sessionId",
                "subjectType",
                "timeSpentMs",
                "title",
                "trackListening",
            }
        )
        return [
            {
                key: UserStateCollections.value(item)
                for key, item in candidate.items()
                if key in allowed and item is not None
            }
            for candidate in value[-5:]
            if isinstance(candidate, dict) and candidate.get("feedbackKey")
        ]

    @staticmethod
    def followed_creators(value) -> list:
        if not isinstance(value, list):
            return []
        normalized = []
        seen = set()
        for item in value:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            source_type = "organization" if item.get("type") == "organization" else "creator"
            key = (source_type, str(item["id"]))
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                {"id": str(item["id"]), "name": item.get("name"), "type": source_type}
            )
        return normalized[-50:]

    @staticmethod
    def publication_progress(value) -> dict:
        if not isinstance(value, dict):
            return {}
        capped = {}
        ordered = sorted(
            value.items(), key=lambda pair: int((pair[1] or {}).get("updatedAt") or 0)
        )[-2:]
        for publication_id, progress in ordered:
            if not isinstance(progress, dict):
                continue
            tracks = progress.get("tracks") or {}
            if isinstance(tracks, dict):
                tracks = {
                    str(content_id): {
                        key: item[key]
                        for key in (
                            "completed",
                            "contentId",
                            "durationMs",
                            "listenedMs",
                            "timeSpentMs",
                            "trackIndex",
                        )
                        if item.get(key) is not None
                    }
                    for content_id, item in list(tracks.items())[-100:]
                    if isinstance(item, dict)
                }
            capped[str(publication_id)] = {
                key: UserStateCollections.value(item)
                for key, item in progress.items()
                if key not in {"sessions", "timeSpentHours", "trackListening"} and item is not None
            }
            capped[str(publication_id)]["tracks"] = tracks
        return capped

class UserStateNormalizer:
    PLAYBACK_FIELDS = frozenset(
        {
            "audioUrl",
            "category",
            "contentId",
            "creatorId",
            "creatorName",
            "discoverySource",
            "discoveryContext",
            "durationMs",
            "eventTimestamp",
            "isPublication",
            "lastEventRequestId",
            "lastListeningDeltaMs",
            "listenedMs",
            "observationOffsetMs",
            "observationTimestampMs",
            "offsetMs",
            "organizationId",
            "organizationName",
            "playbackSpeeds",
            "publicationId",
            "publicationTitle",
            "queueId",
            "queueIndex",
            "sessionId",
            "startedAt",
            "status",
            "subjectSessionId",
            "summary",
            "timeSpentMs",
            "title",
            "trackCount",
            "trackIndex",
            "updatedAt",
        }
    )
    CONTENT_CACHE_FIELDS = frozenset(
        {
            "audioUrl",
            "category",
            "contentId",
            "creatorId",
            "creatorName",
            "durationMs",
            "isPublication",
            "organizationId",
            "organizationName",
            "playbackSpeeds",
            "publicationId",
            "publicationTitle",
            "spokenTitle",
            "summary",
            "title",
            "trackCount",
            "trackIndex",
        }
    )

    @staticmethod
    def value(value, depth: int = 0):
        return UserStateCollections.value(value, depth)

    @staticmethod
    def snapshot(store: dict) -> dict:
        normalized = {
            key: UserStateNormalizer.value(value)
            for key, value in store.items()
            if key in StateSchema.PERSISTED_FIELDS and value != StateSchema.default_for(key)
        }
        active = normalized.get("activePlayback")
        if isinstance(active, dict):
            normalized["activePlayback"] = UserStateNormalizer.active_playback(active)
        queue = normalized.get("playbackQueue")
        if isinstance(queue, dict) and isinstance(queue.get("orderedContentIds"), list):
            queue["orderedContentIds"] = queue["orderedContentIds"][
                : max(settings.HEAR_PERSISTED_COLLECTION_LIMIT, 1)
            ]
            queue["currentIndex"] = min(
                max(0, int(queue.get("currentIndex") or 0)),
                max(len(queue["orderedContentIds"]) - 1, 0),
            )
        prepared = normalized.get("preparedNextContent")
        if isinstance(prepared, dict):
            normalized["preparedNextContent"] = UserStateNormalizer.content_cache(prepared)
        normalized["playHistory"] = UserStateNormalizer.play_history(normalized.get("playHistory"))
        for key in tuple(normalized):
            if normalized[key] == StateSchema.default_for(key):
                normalized.pop(key, None)
        return normalized

    @staticmethod
    def active_playback(value: dict) -> dict:
        return {
            key: UserStateNormalizer.value(item)
            for key, item in value.items()
            if key in UserStateNormalizer.PLAYBACK_FIELDS and item is not None
        }

    @staticmethod
    def content_cache(value: dict) -> dict:
        return {
            key: UserStateNormalizer.value(item)
            for key, item in value.items()
            if key in UserStateNormalizer.CONTENT_CACHE_FIELDS and item is not None
        }

    @staticmethod
    def play_history(value) -> list:
        compact = []
        for raw in value or []:
            item = PlaybackHistoryUtils.normalize(raw)
            if not item:
                continue
            compact.append(
                {
                    key: item[key]
                    for key in (
                        "id",
                        "subjectType",
                        "subjectId",
                        "contentId",
                        "trackContentId",
                        "publicationId",
                        "trackIndex",
                        "trackCount",
                        "offsetMs",
                        "listenedMs",
                        "timeSpentMs",
                        "completed",
                    )
                    if item.get(key) is not None
                }
            )
        return compact[: min(settings.max_history, 20)]

    @staticmethod
    def feedback_candidates(value) -> list:
        return UserStateCollections.feedback_candidates(value)

    @staticmethod
    def followed_creators(value) -> list:
        return UserStateCollections.followed_creators(value)

    @staticmethod
    def publication_progress(value) -> dict:
        return UserStateCollections.publication_progress(value)

    @staticmethod
    def feedback(store: dict) -> None:
        pending = store.get("pendingFeedback")
        if (
            not isinstance(pending, dict)
            or not pending.get("publicationId")
            or pending.get("subjectType") == "publication"
        ):
            return
        store["pendingFeedback"] = None
        store["awaitingFeedback"] = False
        dialog = store.get("activeDialog") or {}
        if (dialog.get("type") or dialog.get("kind")) == "feedback":
            store["activeDialog"] = None
