from __future__ import annotations

from config import settings


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
                if key not in {"sessions", "timeSpentHours", "trackListening"}
                and item is not None
            }
            capped[str(publication_id)]["tracks"] = tracks
        return capped

    @staticmethod
    def history(value) -> list:
        return (
            [item for item in value if isinstance(item, dict)][-100:]
            if isinstance(value, list)
            else []
        )
