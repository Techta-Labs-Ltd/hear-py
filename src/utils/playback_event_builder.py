from __future__ import annotations

import time


def _timestamp_ms(value=None) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    return int(time.time() * 1000)


def build_playback_event(
    *,
    content_id: str,
    session_id: str,
    event_type: str,
    position_ms: int = 0,
    duration_ms: int = 0,
    listened_ms: int = 0,
    creator_id: str | None = None,
    publication_id: str | None = None,
    queue_id: str | None = None,
    timestamp_ms: int | None = None,
) -> dict:
    timestamp = _timestamp_ms(timestamp_ms)
    duration = max(0, int(duration_ms or 0))
    listened = max(0, int(listened_ms or 0))
    return {
        "contentId": str(content_id),
        "creatorId": creator_id,
        "publicationId": publication_id,
        "queueId": queue_id,
        "sessionId": str(session_id),
        "eventType": event_type,
        "positionMs": max(0, int(position_ms or 0)),
        "durationMs": duration,
        "listenedMs": listened,
        "completionPercentage": (
            min(100, round(listened / duration * 100))
            if duration > 0
            else None
        ),
        "timestampMs": timestamp,
        "clientEventId": f"{session_id}:{event_type}:{timestamp}",
    }


def normalize_playback_event(event: dict) -> dict:
    if not isinstance(event, dict):
        return {}
    normalized = dict(event)
    normalized["timestampMs"] = _timestamp_ms(event.get("timestampMs"))
    normalized.setdefault(
        "clientEventId",
        f"{event.get('sessionId')}:{event.get('eventType')}:{normalized['timestampMs']}",
    )
    return normalized
