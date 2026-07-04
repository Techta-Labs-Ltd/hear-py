from __future__ import annotations

import time

from src.services.persistence import get_store, update_store


def get_alexa_user_id(handler_input) -> str | None:
    """Extract the Alexa user ID from the request envelope."""
    try:
        return handler_input.request_envelope.context.System.user.userId or None
    except Exception:
        return None


def get_device_id(handler_input) -> str | None:
    """Extract the Alexa device ID from the request envelope."""
    try:
        return handler_input.request_envelope.context.System.device.deviceId or None
    except Exception:
        return None


def get_locale(handler_input) -> str | None:
    """Extract the locale from the request."""
    try:
        return handler_input.request_envelope.request.locale or None
    except Exception:
        return None


def read_audio_player_context(handler_input) -> dict | None:
    """Read and normalize the Alexa AudioPlayer context."""
    try:
        audio = handler_input.request_envelope.context.AudioPlayer
    except Exception:
        return None
    if not audio or not isinstance(audio, dict):
        return None
    token = str(audio["token"]) if audio.get("token") is not None else None
    offset_ms = max(0, round(audio["offsetInMilliseconds"])) if isinstance(audio.get("offsetInMilliseconds"), (int, float)) else 0
    player_activity = str(audio["playerActivity"]) if audio.get("playerActivity") is not None else None
    if not token and not player_activity and offset_ms == 0:
        return None
    return {"token": token, "offsetMs": offset_ms, "playerActivity": player_activity}


def is_audio_player_active(context: dict | None) -> bool:
    """Check whether the AudioPlayer reports an active playback state."""
    if not context:
        return False
    if not context.get("playerActivity"):
        return bool(context.get("token"))
    return context["playerActivity"] in ("PLAYING", "PAUSED", "BUFFER_UNDERRUN")


def resolve_active_playback_token(store: dict) -> str | None:
    """Resolve the active playback token from the session store."""
    if not isinstance(store, dict):
        return None
    return store.get("lastToken") or store.get("playbackTrackId") or store.get("feedbackContentId") or store.get("currentContentId") or None


def resolve_report_track_context(store: dict, *, audio_token: str | None = None) -> dict:
    """Resolve the track and content IDs for reporting context."""
    if not isinstance(store, dict):
        return {"trackId": None, "contentId": None}
    if store.get("reportContext") and store["reportContext"].get("trackId") and store["reportContext"].get("contentId"):
        return {"trackId": str(store["reportContext"]["trackId"]), "contentId": str(store["reportContext"]["contentId"])}
    pf = store.get("pendingFeedback") or {}
    recent = (store.get("recentTrackListens") or [])[0] if isinstance(store.get("recentTrackListens"), list) and store["recentTrackListens"] else None
    track_id = (
        store.get("playbackTrackId") or store.get("lastToken") or audio_token or
        pf.get("trackId") or (recent.get("trackId") if recent else None) or store.get("feedbackContentId") or None
    )
    content_id = (
        store.get("currentContentId") or store.get("playbackParentId") or
        store.get("currentPublicationId") or (recent.get("contentId") if recent else None) or
        (recent.get("parentId") if recent else None) or track_id
    )
    return {
        "trackId": str(track_id) if track_id is not None else None,
        "contentId": str(content_id) if content_id is not None else None,
    }


def build_report_context(store: dict, *, audio_token: str | None = None) -> dict:
    """Build a full report context including title, creator, and content IDs."""
    if not isinstance(store, dict):
        return {"trackId": None, "contentId": None, "title": None, "creatorId": None, "creatorName": None}
    ctx = resolve_report_track_context(store, audio_token=audio_token)
    pf = store.get("pendingFeedback") or {}
    recent = (store.get("recentTrackListens") or [])[0] if isinstance(store.get("recentTrackListens"), list) and store["recentTrackListens"] else None
    saved = store.get("reportContext") or {}
    return {
        "trackId": ctx["trackId"],
        "contentId": ctx["contentId"],
        "title": saved.get("title") or pf.get("title") or store.get("feedbackContentTitle") or (recent.get("title") if recent else None) or None,
        "creatorId": saved.get("creatorId") or pf.get("creatorId") or store.get("feedbackCreatorId") or (recent.get("creatorId") if recent else None) or None,
        "creatorName": saved.get("creatorName") or pf.get("creatorName") or store.get("feedbackCreator") or None,
    }


def snapshot_report_context(store: dict, *, audio_token: str | None = None) -> dict | None:
    """Capture a snapshot of the current report context for later use."""
    ctx = build_report_context(store, audio_token=audio_token)
    if not ctx.get("trackId") or not ctx.get("contentId"):
        return None
    return {
        "trackId": ctx["trackId"],
        "contentId": ctx["contentId"],
        "title": ctx["title"],
        "creatorId": ctx["creatorId"],
        "creatorName": ctx["creatorName"],
        "capturedAt": int(time.time() * 1000),
    }
