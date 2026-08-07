from __future__ import annotations

import time



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


def resolve_report_track_context(store: dict, *, audio_token: str | None = None) -> dict:
    """Resolve the canonical content ID for reporting context."""
    if not isinstance(store, dict):
        return {"contentId": None}
    if store.get("reportContext") and store["reportContext"].get("contentId"):
        saved = store["reportContext"]
        return {
            "contentId": str(saved["contentId"]),
            "publicationId": saved.get("publicationId"),
        }
    pf = store.get("pendingFeedback") or {}
    active = store.get("activePlayback") or {}
    content_id = pf.get("contentId") or active.get("contentId") or audio_token
    publication_id = pf.get("publicationId") or active.get("publicationId")
    return {
        "contentId": str(content_id) if content_id is not None else None,
        "publicationId": str(publication_id) if publication_id is not None else None,
    }


def build_report_context(store: dict, *, audio_token: str | None = None) -> dict:
    """Build a full report context including title, creator, and content IDs."""
    if not isinstance(store, dict):
        return {"contentId": None, "title": None, "creatorId": None, "creatorName": None}
    ctx = resolve_report_track_context(store, audio_token=audio_token)
    pf = store.get("pendingFeedback") or {}
    active = store.get("activePlayback") or {}
    saved = store.get("reportContext") or {}
    return {
        "contentId": ctx["contentId"],
        "publicationId": saved.get("publicationId") or ctx.get("publicationId"),
        "title": saved.get("title") or pf.get("title") or active.get("title"),
        "creatorId": saved.get("creatorId") or pf.get("creatorId") or active.get("creatorId"),
        "creatorName": saved.get("creatorName") or pf.get("creatorName") or active.get("creatorName"),
    }


def snapshot_report_context(store: dict, *, audio_token: str | None = None) -> dict | None:
    """Capture a snapshot of the current report context for later use."""
    ctx = build_report_context(store, audio_token=audio_token)
    if not ctx.get("contentId"):
        return None
    return {
        "contentId": ctx["contentId"],
        "publicationId": ctx.get("publicationId"),
        "title": ctx["title"],
        "creatorId": ctx["creatorId"],
        "creatorName": ctx["creatorName"],
        "capturedAt": int(time.time() * 1000),
    }
