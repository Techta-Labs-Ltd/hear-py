from __future__ import annotations

import time


def resolve_flush_position_ms(state: dict | None, override_offset_ms=None) -> int:
    """Resolve the best-known playback position for flush/drain operations."""
    if override_offset_ms is not None and isinstance(override_offset_ms, (int, float)):
        return max(0, round(override_offset_ms))
    if state and isinstance(state.get("lastKnownOffsetMs"), (int, float)):
        return max(0, round(state["lastKnownOffsetMs"]))
    wall_start = (state or {}).get("wallStart") or int(time.time() * 1000)
    start_offset_ms = (state or {}).get("startOffsetMs") or 0
    estimated = start_offset_ms + (int(time.time() * 1000) - wall_start)
    if state and isinstance(state.get("trackDurationMs"), (int, float)) and state["trackDurationMs"] > 0:
        estimated = min(estimated, state["trackDurationMs"])
    return max(0, round(estimated))


def duration_ms_from_store(store: dict | None) -> int:
    """Extract track duration in ms from the session store."""
    if not isinstance(store, dict):
        return 0
    if isinstance(store.get("currentDurationSecs"), (int, float)) and store["currentDurationSecs"] > 0:
        return round(store["currentDurationSecs"] * 1000)
    if isinstance(store.get("playbackDurationEstimateMs"), (int, float)) and store["playbackDurationEstimateMs"] > 0:
        return round(store["playbackDurationEstimateMs"])
    return 0


def resolve_track_duration_ms(state: dict | None, store: dict | None, position_ms: int = 0) -> int:
    """Resolve the best estimate of track duration in milliseconds."""
    duration = (state.get("trackDurationMs") if (state and isinstance(state.get("trackDurationMs"), (int, float)) and state["trackDurationMs"] > 0) else 0) or 0
    if not duration:
        duration = duration_ms_from_store(store)
    pos = max(0, round(position_ms or 0))
    last_known = max(0, round((state or {}).get("lastKnownOffsetMs") or 0))
    observed_max = max(pos, last_known)
    if not duration and observed_max > 0:
        return observed_max
    if duration and observed_max > duration:
        return observed_max
    return duration


def resolve_playback_event_timing(state: dict | None, store: dict | None, position_ms: int) -> dict:
    """Resolve position and track duration for a playback event."""
    pos = max(0, round(position_ms or 0))
    track_duration_ms = resolve_track_duration_ms(state, store, pos)
    return {"positionMs": pos, "trackDurationMs": track_duration_ms}


def _resolve_finished_position_ms(state: dict | None, offset_ms: int, store: dict | None) -> int:
    """Determine the final position for a finished event."""
    track_duration_ms = resolve_track_duration_ms(state, store, offset_ms)
    reported_offset = max(0, round(offset_ms or 0))
    last_known = max(0, round((state or {}).get("lastKnownOffsetMs") or 0))
    if reported_offset > 0:
        return min(reported_offset, track_duration_ms) if track_duration_ms > 0 else reported_offset
    if last_known > 0:
        return min(last_known, track_duration_ms) if track_duration_ms > 0 else last_known
    if track_duration_ms > 0:
        return track_duration_ms
    return resolve_flush_position_ms(state or {}, offset_ms)


def resolve_finished_event_timing(state: dict | None, store: dict | None, offset_ms: int) -> dict:
    """Resolve timing for a playback-finished event."""
    position_ms = _resolve_finished_position_ms(state, offset_ms, store)
    track_duration_ms = resolve_track_duration_ms(state, store, position_ms)
    return {"positionMs": position_ms, "trackDurationMs": max(track_duration_ms, position_ms)}


def playback_state_duration_patch(state: dict | None, store: dict | None, position_ms: int) -> dict:
    """Build a duration-only patch for the playback state."""
    duration_ms = resolve_track_duration_ms(state, store, position_ms)
    if not duration_ms:
        return {}
    return {"trackDurationMs": duration_ms}
