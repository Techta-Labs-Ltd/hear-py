from __future__ import annotations

import re

from config import settings
from src.services.store import update_store

from src.utils.feedback_timing import feedback_progress_report_options
from src.utils.normalize_content_item import is_id_like_label


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
    if isinstance(cat, dict):
        cat = cat.get("name") or cat.get("slug")
    locality = content.get("locality")
    if isinstance(locality, dict):
        locality = locality.get("name") or locality.get("slug")
    subtitle = [str(c) for c in [cat, locality] if c]
    tags = content.get("tags") or []
    if tags:
        subtitle.append(", ".join([str(t) for t in tags]))
    track_candidate = (track_title or "").strip()
    parent_candidate = (
        content.get("spokenTitle")
        or content.get("title")
        or ""
    ).strip()
    if track_candidate and not is_id_like_label(track_candidate):
        title = track_candidate
    elif parent_candidate and not is_id_like_label(parent_candidate):
        title = parent_candidate
    else:
        title = parent_candidate or track_candidate or "Hear"
    subtitle_str = " \u00b7 ".join(subtitle)
    return {"title": title, "subtitle": subtitle_str}


def normalise_speed(requested) -> float | None:
    """Return an exact configured speed; never guess from a misheard value."""
    aliases = {
        "first": 0.5, "first speed": 0.5, "half": 0.5, "half speed": 0.5,
        "second": 0.75, "second speed": 0.75, "three quarter speed": 0.75,
        "third": 1.0, "third speed": 1.0, "normal": 1.0,
        "normal speed": 1.0, "regular speed": 1.0, "reset speed": 1.0,
        "fourth": 1.25, "fourth speed": 1.25,
        "fifth": 1.5, "fifth speed": 1.5, "one and a half": 1.5,
        "sixth": 2.0, "sixth speed": 2.0, "double": 2.0, "double speed": 2.0,
    }
    raw = str(requested).strip().casefold() if requested is not None else ""
    if raw in aliases:
        return aliases[raw]
    try:
        spd = float(raw.removesuffix("x").strip())
    except (TypeError, ValueError):
        return None
    return next((speed for speed in settings.speeds if abs(speed - spd) < 0.001), None)


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
