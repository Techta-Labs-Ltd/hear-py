from __future__ import annotations

import time

from config import settings
from src.utils.audio import parse_playback_speed_from_url


def _pick_string(*values) -> str | None:
    """Pick the first non-empty string from candidates."""
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def resolve_playback_event_media(store: dict | None, state: dict | None) -> dict:
    """Resolve the audio URL and playback speed for a playback event."""
    audio_url = _pick_string(
        (state or {}).get("currentAudioUrl") if state else None,
        (store or {}).get("currentAudioUrl") if store else None,
        ((store or {}).get("playbackSession") or {}).get("currentAudioUrl") if store else None,
    )
    store_speed = store.get("playbackSpeed") if (store and isinstance(store.get("playbackSpeed"), (int, float))) else None
    state_speed = state.get("playbackSpeed") if (state and isinstance(state.get("playbackSpeed"), (int, float))) else None
    fallback_speed = state_speed if state_speed is not None else store_speed if store_speed is not None else settings.default_speed
    playback_speed = parse_playback_speed_from_url(audio_url, fallback_speed) if audio_url else fallback_speed
    return {"audioUrl": audio_url, "playbackSpeed": playback_speed}


def _parse_timestamp_ms(value) -> int | None:
    """Parse a timestamp value into milliseconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(value)
    try:
        parsed = time.mktime(time.strptime(str(value), "%Y-%m-%dT%H:%M:%S.%fZ"))
        return round(parsed * 1000)
    except Exception:
        pass
    return None


def _resolve_playback_event_timestamps(skill_timestamp_ms, alexa_timestamp=None) -> dict:
    """Resolve ISO-8601 and millisecond timestamps for a playback event."""
    timestamp_ms = _parse_timestamp_ms(skill_timestamp_ms) or int(time.time() * 1000)
    ts_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(timestamp_ms / 1000)) + f".{timestamp_ms % 1000:03d}Z"
    result = {"timestamp": ts_iso, "timestampMs": timestamp_ms}
    alexa_ts = _parse_timestamp_ms(alexa_timestamp)
    if alexa_ts is not None:
        result["alexaTimestampMs"] = alexa_ts
        result["alexaTimestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(alexa_ts / 1000)) + f".{alexa_ts % 1000:03d}Z"
    return result


def alexa_timestamp_from_request(request: dict | None) -> str | None:
    """Extract the Alexa request timestamp."""
    return (request or {}).get("timestamp") or None


def _build_client_event_id(session_id: str, event_label: str, timestamp) -> str:
    """Build a unique client event ID."""
    ts = _parse_timestamp_ms(timestamp) or int(time.time() * 1000)
    return f"{session_id}-{event_label}-{ts}"


def build_playback_event(*, session_id=None, track_id=None, event_type=None, position_ms=None, track_duration_ms=None, event_label=None, timestamp=None, alexa_timestamp=None, audio_url=None, playback_speed=None) -> dict:
    """Build a complete playback event payload."""
    label = event_label or event_type
    timestamps = _resolve_playback_event_timestamps(timestamp, alexa_timestamp)
    event = {
        "trackId": str(track_id),
        "sessionId": str(session_id),
        "eventType": event_type,
        "positionMs": max(0, round(position_ms or 0)),
        "trackDurationMs": max(0, round(track_duration_ms or 0)),
        **timestamps,
        "clientEventId": _build_client_event_id(session_id, label, timestamps["timestampMs"]),
    }
    if audio_url:
        event["audioUrl"] = audio_url
    if playback_speed is not None:
        try:
            event["playbackSpeed"] = float(playback_speed)
        except (ValueError, TypeError):
            pass
    return event


def normalize_playback_event(event: dict) -> dict:
    """Normalize timestamps on an existing playback event."""
    if not isinstance(event, dict):
        return event
    timestamps = _resolve_playback_event_timestamps(
        event.get("timestampMs") or event.get("timestamp"),
        event.get("alexaTimestampMs") or event.get("alexaTimestamp"),
    )
    return {**event, **timestamps}


def normalize_playback_event_timestamp(timestamp) -> str:
    """Normalize a raw timestamp into an ISO-8601 string."""
    return _resolve_playback_event_timestamps(timestamp)["timestamp"]
