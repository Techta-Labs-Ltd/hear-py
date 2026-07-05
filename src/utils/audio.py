from __future__ import annotations

import re
from urllib.parse import urlparse, parse_qs

from config import settings
from src.services.persistence import update_store
from src.utils.feedback_timing import feedback_progress_report_options
from src.utils.normalize_content_item import is_id_like_label, nullable_string
from src.utils.content_playback import resolve_playback_at_track_index


def _normalize_audio_item_metadata(metadata: dict | None) -> dict | None:
    if not metadata or not isinstance(metadata, dict):
        return None
    title = metadata.get("title")
    subtitle = metadata.get("subtitle")
    if not isinstance(title, str) or not isinstance(subtitle, str) or not title.strip():
        return None
    return {
        "title": title.strip(),
        "subtitle": subtitle,
    }


def build_play_directive(options=None, *, url=None, token=None, offset_ms: int = 0, prev_token=None, metadata=None, progress_report: bool = False, duration_secs=None, handler_input=None) -> dict | None:
    """Build an AudioPlayer.Play directive with optional progress report configuration.

    Accepts either keyword arguments or a single options dict (camelCase keys),
    for compatibility with call sites ported from JavaScript.
    """
    if isinstance(options, dict):
        url = options.get("url", url)
        token = options.get("token", token)
        offset_ms = options.get("offsetMs", options.get("offset_ms", offset_ms))
        prev_token = options.get("prevToken", options.get("prev_token", prev_token))
        metadata = options.get("metadata", metadata)
        progress_report = options.get("progressReport", options.get("progress_report", progress_report))
        duration_secs = options.get("durationSecs", options.get("duration_secs", duration_secs))
        handler_input = options.get("handlerInput", options.get("handler_input", handler_input))
    if not url or not token:
        return None
    if handler_input and url:
        try:
            update_store(handler_input, {"currentAudioUrl": url})
        except Exception:
            pass
    stream: dict = {"url": url, "token": token, "offsetInMilliseconds": offset_ms}
    if progress_report:
        opts = feedback_progress_report_options(duration_secs)
        stream["progressReportDelayInMilliseconds"] = opts["progressReportDelayInMilliseconds"]
        stream["progressReportIntervalInMilliseconds"] = opts["progressReportIntervalInMilliseconds"]
    audio_item: dict = {"stream": stream}
    normalized = _normalize_audio_item_metadata(metadata)
    if normalized:
        audio_item["metadata"] = normalized
    directive: dict = {
        "type": "AudioPlayer.Play",
        "playBehavior": "ENQUEUE" if prev_token else "REPLACE_ALL",
        "audioItem": audio_item,
    }
    if prev_token:
        directive["audioItem"]["stream"]["expectedPreviousToken"] = prev_token
    return directive


def build_stop_directive() -> dict:
    """Build an AudioPlayer.Stop directive."""
    return {"type": "AudioPlayer.Stop"}


def build_content_metadata(content: dict, track_title: str | None = None, resolved_category: str | None = None) -> dict:
    cat = resolved_category if resolved_category else content.get("category") or (content.get("categories") or [None])[0]
    subtitle = [c for c in [cat, content.get("locality")] if c]
    tags = content.get("tags") or []
    if tags:
        subtitle.append(", ".join([str(t) for t in tags]))
    track_candidate = (track_title or "").strip()
    parent_candidate = (content.get("title") or "").strip()
    if track_candidate and not is_id_like_label(track_candidate):
        title = track_candidate
    elif parent_candidate and not is_id_like_label(parent_candidate):
        title = parent_candidate
    else:
        title = parent_candidate or track_candidate or "Hear"
    subtitle_str = " \u00b7 ".join(subtitle)
    return {"title": title, "subtitle": subtitle_str}


def normalise_speed(requested) -> float | None:
    """Snap a requested speed value to the nearest configured speed."""
    spd = float(requested) if requested is not None else None
    if spd is None or (isinstance(spd, float) and (spd != spd)):
        return None
    speeds = settings.speeds
    best = speeds[0]
    best_diff = abs(best - spd)
    for s in speeds[1:]:
        diff = abs(s - spd)
        if diff < best_diff:
            best_diff = diff
            best = s
    return best


def apply_speed_to_url(url: str | None, speed) -> str | None:
    """Inject or replace the speed query parameter on an audio URL."""
    if not url or not isinstance(url, str):
        return url
    numeric_speed = float(speed) if speed is not None else None
    if numeric_speed is None or numeric_speed != numeric_speed or numeric_speed == settings.default_speed:
        return url
    param = settings.HEAR_AUDIO_SPEED_PARAM or "speed"
    pattern = re.compile(rf"([?&]){re.escape(param)}=[^&]*")
    if pattern.search(url):
        return pattern.sub(rf"\1{param}={numeric_speed}", url)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{param}={numeric_speed}"


def find_speed_url(speeds: list | None, target_speed: float) -> str | None:
    """Find the best-matching speed-variant audio URL within tolerance."""
    if not isinstance(speeds, list) or not speeds:
        return None
    closest = None
    closest_diff = float("inf")
    for entry in speeds:
        diff = abs(entry["speed"] - target_speed)
        if diff < closest_diff and diff < 0.15:
            closest_diff = diff
            closest = entry.get("audioUrl")
    return closest


def get_next_speed(speeds: list | None, current_speed: float, direction: str) -> dict | None:
    """Find the next higher or lower speed entry from a speeds list."""
    if not isinstance(speeds, list) or not speeds:
        return None
    sorted_speeds = sorted(speeds, key=lambda e: e["speed"])
    if direction == "up":
        for entry in sorted_speeds:
            if entry["speed"] > current_speed + 0.01:
                return entry
        return None
    for i in range(len(sorted_speeds) - 1, -1, -1):
        if sorted_speeds[i]["speed"] < current_speed - 0.01:
            return sorted_speeds[i]
    return None


def get_next_configured_speed(current_speed: float, direction: str, speeds: list | None = None) -> float | None:
    """Find the next higher or lower speed from the configured speed list."""
    lst = list(speeds) if speeds else settings.speeds
    if not lst:
        return None
    sorted_lst = sorted(lst)
    if direction == "up":
        for s in sorted_lst:
            if s > current_speed + 0.01:
                return s
        return None
    for i in range(len(sorted_lst) - 1, -1, -1):
        if sorted_lst[i] < current_speed - 0.01:
            return sorted_lst[i]
    return None


def strip_speed_from_url(url: str | None) -> str | None:
    """Remove the speed query parameter from an audio URL."""
    if not url or not isinstance(url, str):
        return url
    param = settings.HEAR_AUDIO_SPEED_PARAM or "speed"
    pattern = re.compile(rf"([?&]){re.escape(param)}=[^&]*")
    cleaned = pattern.sub(lambda m: "?" if m.group(1) == "?" else "", url)
    cleaned = re.sub(r"\?&", "?", cleaned)
    cleaned = re.sub(r"\?$", "", cleaned)
    return cleaned


def resolve_effective_playback_speed(speed, playback_speeds: list | None) -> float:
    """Resolve the effective playback speed, falling back to default if variant is unavailable."""
    numeric = float(speed) if speed is not None else None
    if numeric is None or numeric != numeric or numeric == settings.default_speed:
        return settings.default_speed
    if not isinstance(playback_speeds, list) or not playback_speeds:
        return settings.default_speed
    return numeric if find_speed_url(playback_speeds, numeric) else settings.default_speed


def resolve_audio_url_for_speed(base_url: str | None, speed, playback_speeds: list | None) -> str | None:
    """Resolve the best audio URL for a given playback speed."""
    if not base_url or not isinstance(base_url, str):
        return base_url
    effective = resolve_effective_playback_speed(speed, playback_speeds)
    if effective == settings.default_speed:
        return strip_speed_from_url(base_url)
    variant = find_speed_url(playback_speeds, effective)
    return variant or strip_speed_from_url(base_url)


def _parse_playback_speed_from_filename(url: str) -> float | None:
    """Extract a playback speed from a filename suffix like _1.5x."""
    if not url or not isinstance(url, str):
        return None
    m = re.search(r"_([\d.]+)x(?:[.?]|$)", url, re.I)
    return normalise_speed(float(m.group(1))) if m else None


def parse_playback_speed_from_url(url: str | None, fallback_speed=None) -> float:
    """Parse the playback speed from a URL query parameter or filename."""
    fallback = float(fallback_speed) if (fallback_speed is not None and isinstance(fallback_speed, (int, float))) else settings.default_speed
    if not url or not isinstance(url, str):
        return fallback
    param = settings.HEAR_AUDIO_SPEED_PARAM or "speed"
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        from_query = qs.get(param, [None])[0]
        if from_query is not None:
            spd = normalise_speed(from_query)
            if spd:
                return spd
    except Exception:
        m = re.search(rf"[?&]{re.escape(param)}=([^&]+)", url)
        if m:
            spd = normalise_speed(m.group(1))
            if spd:
                return spd
    from_filename = _parse_playback_speed_from_filename(url)
    return from_filename or fallback


def parse_duration_to_ms(duration: str | None) -> int | None:
    """Convert an ISO-8601 duration string to milliseconds."""
    if not duration:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not m:
        return None
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    return (hours * 3600 + minutes * 60 + seconds) * 1000


def resolve_seek_ms(handler_input) -> int:
    """Extract a seek offset in ms from the intent slots or fall back to default."""
    try:
        intent = handler_input.request_envelope.request.intent
        slots = (intent.get("slots") if intent else None) or {}
        duration_val = (slots.get("time") or {}).get("value") if isinstance(slots.get("time"), dict) else None
        number_val = (slots.get("number") or {}).get("value") if isinstance(slots.get("number"), dict) else None
        from_duration = parse_duration_to_ms(duration_val)
        if from_duration:
            return from_duration
        num = int(number_val) if number_val is not None else None
        if num is not None:
            return num * 1000
    except Exception:
        pass
    return settings.seek_step_ms


def resolve_track_audio(content: dict, track_index: int = 0) -> dict | None:
    """Resolve the audio URL, token, and metadata for a track at the given index."""
    resolved = resolve_playback_at_track_index(content, track_index)
    if not resolved:
        return None
    return {
        "audioUrl": resolved["audioUrl"],
        "token": resolved["token"],
        "trackTitle": resolved["trackTitle"],
        "trackId": resolved["trackId"],
        "playbackParentId": resolved["playbackParentId"],
        "effectiveCategory": resolved["effectiveCategory"],
        "contentType": resolved["contentType"],
        "collectionTitle": resolved["collectionTitle"],
        "totalTracks": resolved["totalTracks"],
        "trackIndex": resolved["trackIndex"],
        "isMultiTrack": resolved["isMultiTrack"],
        "isPublication": resolved["isMultiTrack"],
    }
