from __future__ import annotations

from src.utils.listen_tracker import completion_pct


def _format_listen_time_for_log(ms) -> str:
    """Format a millisecond duration as a human-readable time string."""
    if ms is None or ms != ms or ms <= 0:
        return "0s"
    total_secs = round(ms / 1000)
    mins = total_secs // 60
    secs = total_secs % 60
    if mins > 0:
        return f"{mins}m {secs}s"
    return f"{secs}s"


def summarize_listen_ms(listened_ms, duration_secs) -> dict:
    """Summarize listen duration with completion percentage and formatted time."""
    ms = max(0, round(listened_ms or 0))
    pct = completion_pct(ms, duration_secs)
    return {
        "listenedMs": ms,
        "listenedSecs": round(ms / 1000),
        "timeSpent": _format_listen_time_for_log(ms),
        "completionPct": pct,
    }


def _summarize_playback_event_for_log(event: dict | None) -> dict | None:
    """Summarize a single playback event for logging."""
    if not isinstance(event, dict):
        return None
    position_ms = max(0, round(event.get("positionMs") or 0))
    track_duration_ms = max(0, round(event.get("trackDurationMs") or 0))
    duration_secs = track_duration_ms / 1000 if track_duration_ms > 0 else None
    return {
        "eventType": event.get("eventType") or None,
        "trackId": event.get("trackId") or None,
        "positionMs": position_ms,
        "trackDurationMs": track_duration_ms,
        **summarize_listen_ms(position_ms, duration_secs),
    }


def summarize_playback_events_for_log(events: list) -> list:
    """Summarize a list of playback events for logging."""
    if not isinstance(events, list):
        return []
    return [e for e in (_summarize_playback_event_for_log(ev) for ev in events) if e]


def summarize_recent_plays_for_log(recent_plays: list) -> list:
    """Summarize a list of recent track plays for logging."""
    if not isinstance(recent_plays, list):
        return []
    return [
        {
            "trackId": e.get("trackId") or None,
            "contentId": e.get("contentId") or None,
            "listenedMs": max(0, round(e.get("listenedMs") or 0)),
            "listenedSecs": round((e.get("listenedMs") or 0) / 1000),
            "timeSpent": _format_listen_time_for_log(e.get("listenedMs")),
            "completionPct": e.get("completionPct") if "completionPct" in e else None,
        }
        for e in recent_plays if isinstance(e, dict)
    ]
