from __future__ import annotations

from config import settings
from src.utils.audio import normalise_speed, parse_duration_to_ms
from src.utils.skill_request import get_request_type, get_intent_name


def extract_speed_slot(handler_input) -> float | None:
    """Extract and normalize a playback speed value from the intent slots."""
    try:
        slots = (handler_input.request_envelope.request.intent.get("slots") if handler_input.request_envelope.request.intent else None) or {}
        speed_slot = slots.get("speed")
        raw = (speed_slot.value if speed_slot else None) or ""
        return normalise_speed(raw)
    except Exception:
        return None


def extract_seek_slot(handler_input) -> dict:
    """Extract a seek offset in milliseconds from the intent slots."""
    try:
        slots = (handler_input.request_envelope.request.intent.get("slots") if handler_input.request_envelope.request.intent else None) or {}
        duration_val = (slots.get("time").value if slots.get("time") else None) or None
        number_val = (slots.get("number").value if slots.get("number") else None) or None
    except Exception:
        duration_val = None
        number_val = None

    from_duration = parse_duration_to_ms(duration_val) if duration_val else None
    if from_duration:
        return {"seekMs": from_duration, "source": "duration"}
    try:
        num = int(number_val) if number_val else None
        if num is not None:
            return {"seekMs": num * 1000, "source": "number"}
    except (ValueError, TypeError):
        pass
    return {"seekMs": settings.seek_step_ms, "source": "default"}


def get_intent_tag(handler_input) -> str | None:
    """Get a short tag describing the current intent for analytics."""
    rt = get_request_type(handler_input)
    if rt == "AudioPlayer.PlaybackNearlyFinished":
        return "nearly_finished_refill"
    if rt == "AudioPlayer.PlaybackFailed":
        return "failed_recovery"
    if rt != "IntentRequest":
        return None
    name = get_intent_name(handler_input)
    mapping = {
        "PlayContentIntent": "play",
        "BrowseContentIntent": "browse",
        "WhatsTrendingIntent": "trending",
        "AMAZON.NextIntent": "next",
        "AMAZON.PreviousIntent": "previous",
        "AMAZON.ResumeIntent": "resume",
        "AMAZON.RepeatIntent": "repeat",
        "AMAZON.StartOverIntent": "repeat",
    }
    return mapping.get(name)
