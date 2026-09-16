from __future__ import annotations

from config import settings
from src.utils.playback_history import PlaybackHistoryUtils


class PlaybackHistory:
    @staticmethod
    def add(history_items: object, content_or_id: object) -> list[dict]:
        """Return a new history after adding an item or publication cursor."""
        raw_items = history_items if isinstance(history_items, (list, tuple)) else ()
        history = [
            normalized
            for item in raw_items
            if (normalized := PlaybackHistoryUtils.normalize(item))
        ]
        if isinstance(content_or_id, dict) and content_or_id.get("audioUrl"):
            entry = PlaybackHistoryUtils.normalize(content_or_id)
            if not entry:
                return history
            subject_id = entry["subjectId"]
        else:
            subject_id = str(content_or_id) if content_or_id is not None else None
            entry = PlaybackHistoryUtils.normalize(subject_id) if subject_id else None
        if not subject_id or not entry:
            return history
        previous = next(
            (
                history.pop(index)
                for index, item in enumerate(history)
                if item.get("subjectId") == subject_id or item["id"] == subject_id
            ),
            None,
        )
        if previous:
            PlaybackHistory._preserve_progress(entry, previous)
        history.insert(0, entry)
        return history[: settings.max_history]

    @staticmethod
    def update(
        history_items: object,
        state: dict,
        *,
        completed: bool = False,
    ) -> list[dict]:
        subject_id = state.get("publicationId") or state.get("contentId")
        raw_items = history_items if isinstance(history_items, (list, tuple)) else ()
        history = [
            normalized
            for item in raw_items
            if (normalized := PlaybackHistoryUtils.normalize(item))
        ]
        index = next(
            (
                position
                for position, item in enumerate(history)
                if item.get("subjectId") == subject_id
            ),
            None,
        )
        existing = history.pop(index) if index is not None else None
        updated = PlaybackHistoryUtils.merge(
            existing,
            state,
            completed=completed,
        )
        if updated:
            history.insert(0, updated)
        return history[: settings.max_history]
    @staticmethod
    def _preserve_progress(entry: dict, previous: dict) -> None:
        for key in (
            "offsetMs",
            "listenedMs",
            "timeSpentMs",
            "timeSpentHours",
            "completed",
            "sessions",
            "tracks",
        ):
            if previous.get(key) is not None:
                entry[key] = previous[key]
