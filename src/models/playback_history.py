from __future__ import annotations

from config import settings
from src.models.user import User
from src.utils.playback_history import PlaybackHistoryUtils


class PlaybackHistory:
    @staticmethod
    def add(handler_input, content_or_id, recording_id: str | None = None) -> dict:
        """Add one standalone item or publication cursor to play history."""
        store = User.snapshot(handler_input)
        history = [
            normalized
            for item in store.get("playHistory") or []
            if (normalized := PlaybackHistoryUtils.normalize(item))
        ]
        if isinstance(content_or_id, dict) and content_or_id.get("audioUrl"):
            entry = PlaybackHistoryUtils.normalize(content_or_id)
            if not entry:
                return store
            subject_id = entry["subjectId"]
        else:
            subject_id = str(content_or_id) if content_or_id is not None else None
            entry = PlaybackHistoryUtils.normalize(subject_id) if subject_id else None
        if not subject_id or not entry:
            return store
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
        return User.update(handler_input, {"playHistory": history[: settings.max_history]})

    @staticmethod
    def update(
        handler_input,
        state: dict,
        *,
        completed: bool = False,
    ) -> dict:
        store = User.snapshot(handler_input)
        subject_id = state.get("publicationId") or state.get("contentId")
        history = [
            normalized
            for item in store.get("playHistory") or []
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
        return User.update(handler_input, {"playHistory": history[: settings.max_history]})

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
