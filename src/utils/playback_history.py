from __future__ import annotations

from src.utils.content import ContentIdentity
from src.utils.playback import PlaybackUtils


class PlaybackHistoryUtils:
    @staticmethod
    def normalize(entry) -> dict | None:
        if isinstance(entry, str):
            return {
                "id": entry,
                "subjectType": "content",
                "subjectId": entry,
                "contentId": entry,
            }
        if not isinstance(entry, dict):
            return None
        subject_id = ContentIdentity.subject_id(entry)
        if not subject_id:
            return None
        publication = ContentIdentity.is_publication(entry)
        normalized = {
            "id": subject_id,
            "subjectType": "publication" if publication else "content",
            "subjectId": subject_id,
            "contentId": None if publication else ContentIdentity.content_id(entry),
            "trackContentId": ContentIdentity.content_id(entry) if publication else None,
            "publicationId": ContentIdentity.publication_id(entry),
            "publicationTitle": entry.get("publicationTitle"),
            "title": ContentIdentity.subject_title(entry),
            "audioUrl": entry.get("audioUrl"),
            "durationSecs": entry.get("durationSecs") if "durationSecs" in entry else None,
            "durationMs": entry.get("durationMs"),
            "trackIndex": entry.get("trackIndex"),
            "trackCount": entry.get("trackCount"),
            "playback_speed": entry.get("playback_speed")
            if entry.get("playback_speed")
            else None,
            "creator": entry.get("creator") or entry.get("creatorName"),
            "creatorId": entry.get("creatorId"),
            "organizationId": entry.get("organizationId"),
            "organizationName": entry.get("organizationName"),
            "category": entry.get("category"),
            "summary": entry.get("summary"),
            "offsetMs": entry.get("offsetMs"),
            "listenedMs": entry.get("listenedMs"),
            "timeSpentMs": entry.get("timeSpentMs"),
            "timeSpentHours": entry.get("timeSpentHours"),
            "completed": entry.get("completed"),
            "sessions": entry.get("sessions")
            if isinstance(entry.get("sessions"), dict)
            else None,
            "tracks": entry.get("tracks")
            if isinstance(entry.get("tracks"), dict)
            else None,
        }
        return {key: value for key, value in normalized.items() if value is not None}

    @staticmethod
    def session_ledger(existing: dict, state: dict) -> dict:
        sessions = dict(existing.get("sessions") or {})
        session_id = PlaybackHistoryUtils._session_id(state)
        previous = dict(sessions.get(session_id) or {})
        time_spent = max(
            int(previous.get("timeSpentMs") or 0),
            int(state.get("timeSpentMs") or 0),
        )
        sessions[session_id] = {
            "timeSpentMs": time_spent,
            "timeSpentHours": PlaybackUtils.hours(time_spent),
            "lastPositionMs": max(0, int(state.get("offsetMs") or 0)),
            "updatedAt": max(0, int(state.get("updatedAt") or 0)),
        }
        return dict(list(sessions.items())[-20:])

    @staticmethod
    def accumulated_time(existing: dict, state: dict, sessions: dict) -> int:
        session_id = PlaybackHistoryUtils._session_id(state)
        previous_sessions = existing.get("sessions") or {}
        previous_session = previous_sessions.get(session_id) or {}
        current_session = sessions.get(session_id) or {}
        prior_total = existing.get("timeSpentMs")
        if prior_total is None:
            prior_total = PlaybackHistoryUtils._sum_time(previous_sessions)
        if not previous_sessions:
            return max(
                0,
                int(prior_total or 0),
                int(current_session.get("timeSpentMs") or 0),
            )
        session_delta = max(
            0,
            int(current_session.get("timeSpentMs") or 0)
            - int(previous_session.get("timeSpentMs") or 0),
        )
        return max(0, int(prior_total or 0)) + session_delta

    @staticmethod
    def merge(
        entry: dict | None,
        state: dict,
        *,
        completed: bool = False,
    ) -> dict | None:
        base = PlaybackHistoryUtils.normalize(entry or state)
        subject_id = ContentIdentity.subject_id(state)
        content_id = ContentIdentity.content_id(state)
        if not base or not subject_id or not content_id:
            return base
        if ContentIdentity.is_publication(state):
            return PlaybackHistoryUtils._merge_publication(
                base,
                state,
                subject_id=str(subject_id),
                content_id=content_id,
                completed=completed,
            )
        return PlaybackHistoryUtils._merge_content(
            base,
            state,
            content_id=content_id,
            completed=completed,
        )

    @staticmethod
    def _merge_publication(
        base: dict,
        state: dict,
        *,
        subject_id: str,
        content_id: str,
        completed: bool,
    ) -> dict:
        tracks = dict(base.get("tracks") or {})
        track = dict(tracks.get(content_id) or {})
        sessions = PlaybackHistoryUtils.session_ledger(track, state)
        track_time = PlaybackHistoryUtils.accumulated_time(track, state, sessions)
        tracks[content_id] = PlaybackHistoryUtils._track_progress(
            track,
            state,
            content_id=content_id,
            completed=completed,
            sessions=sessions,
            time_spent=track_time,
        )
        tracks = dict(list(tracks.items())[-100:])
        total = PlaybackHistoryUtils._sum_time(tracks)
        return {
            **base,
            "id": subject_id,
            "subjectType": "publication",
            "subjectId": subject_id,
            "publicationId": subject_id,
            "trackContentId": content_id,
            "trackIndex": state.get("trackIndex"),
            "trackCount": state.get("trackCount"),
            "offsetMs": max(0, int(state.get("offsetMs") or 0)),
            "listenedMs": max(
                int(base.get("listenedMs") or 0),
                int(state.get("listenedMs") or 0),
            ),
            "timeSpentMs": total,
            "timeSpentHours": PlaybackUtils.hours(total),
            "tracks": tracks,
        }

    @staticmethod
    def _track_progress(
        previous: dict,
        state: dict,
        *,
        content_id: str,
        completed: bool,
        sessions: dict,
        time_spent: int,
    ) -> dict:
        return {
            "contentId": content_id,
            "trackIndex": state.get("trackIndex"),
            "durationMs": state.get("durationMs"),
            "offsetMs": max(0, int(state.get("offsetMs") or 0)),
            "listenedMs": max(
                int(previous.get("listenedMs") or 0),
                int(state.get("listenedMs") or 0),
            ),
            "timeSpentMs": time_spent,
            "timeSpentHours": PlaybackUtils.hours(time_spent),
            "completed": bool(previous.get("completed") or completed),
            "sessions": sessions,
        }

    @staticmethod
    def _merge_content(
        base: dict,
        state: dict,
        *,
        content_id: str,
        completed: bool,
    ) -> dict:
        sessions = PlaybackHistoryUtils.session_ledger(base, state)
        total = PlaybackHistoryUtils.accumulated_time(base, state, sessions)
        return {
            **base,
            "id": content_id,
            "subjectType": "content",
            "subjectId": content_id,
            "contentId": content_id,
            "offsetMs": max(0, int(state.get("offsetMs") or 0)),
            "listenedMs": max(
                int(base.get("listenedMs") or 0),
                int(state.get("listenedMs") or 0),
            ),
            "timeSpentMs": total,
            "timeSpentHours": PlaybackUtils.hours(total),
            "completed": bool(base.get("completed") or completed),
            "sessions": sessions,
        }

    @staticmethod
    def _sum_time(values: dict) -> int:
        return sum(
            int(value.get("timeSpentMs") or 0)
            for value in values.values()
            if isinstance(value, dict)
        )

    @staticmethod
    def _session_id(state: dict) -> str:
        return str(
            state.get("sessionId")
            or state.get("subjectSessionId")
            or ContentIdentity.subject_id(state)
        )
