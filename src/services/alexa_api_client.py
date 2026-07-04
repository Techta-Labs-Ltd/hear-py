from __future__ import annotations
import time
from urllib.parse import quote
from src.services.persistence import get_store
from src.utils.playback_context import get_alexa_user_id, get_device_id, get_locale
from src.utils.playback_event_builder import normalize_playback_event
from src.utils.listen_log import summarize_playback_events_for_log
from src.services.api_request import api_request
from src.webhooks.dispatch import dispatch


async def send_playback_events(
    *,
    alexa_user_id: str,
    events: list,
    refresh_track_ids: list | None = None,
    handler_input=None,
) -> dict:
    """Dispatch playback lifecycle events to the internal webhook channels.

    Each event is dispatched to the corresponding webhook channel
    (playback.started, playback.stopped, playback.finished, etc.). This function
    does not call the Hear API directly and does not aggregate stats.

    Returns ``{"refreshedStats": [], "inserted": None, "status": ...}`` where
    ``status`` is ``"dispatched"`` when events were sent and ``None`` when there
    was nothing to dispatch. ``refreshedStats``/``inserted`` are always empty and
    kept only for backwards-compatible call sites.
    """
    if not alexa_user_id or not isinstance(events, list) or not events:
        return {"refreshedStats": [], "inserted": None, "status": None}

    normalized = [normalize_playback_event(e) for e in events]

    listener_id = None
    if handler_input is not None:
        try:
            store = get_store(handler_input)
            listener_id = store.get("listenerId") or None
        except Exception:
            pass

    for evt in normalized:
        event_type = evt.get("eventType")
        base = {
            "userId": alexa_user_id,
            "listenerId": listener_id,
            "trackId": evt["trackId"],
            "timestamp": int(time.time() * 1000),
            "positionMs": evt["positionMs"],
            "trackDurationMs": evt["trackDurationMs"],
        }

        try:
            if event_type == "AUDIO_PLAYER_PLAYBACK_STARTED":
                dispatch("playback.started", base)
            elif event_type == "AUDIO_PLAYER_PLAYBACK_STOPPED":
                dispatch("playback.stopped", base)
            elif event_type == "AUDIO_PLAYER_PLAYBACK_FINISHED":
                dispatch("playback.finished", base)
            elif event_type == "AUDIO_PLAYER_PLAYBACK_NEARLY_FINISHED":
                dispatch("playback.nearly_finished", base)
            else:
                dispatch("playback.event", {**base, "eventType": event_type})
        except Exception:
            pass

    return {"refreshedStats": [], "inserted": None, "status": "dispatched"}


async def get_playback_stats(alexa_user_id: str, track_id: str) -> dict | None:
    """Retrieve aggregated playback statistics for a specific track."""
    if not alexa_user_id or not track_id:
        return None
    path = f"/listeners/{quote(alexa_user_id)}/playback/stats?trackId={quote(track_id)}"
    try:
        data = await api_request("GET", path)
    except Exception:
        return None
    if isinstance(data, dict):
        stats = data.get("stats")
        if isinstance(stats, dict) and not isinstance(stats, list):
            return stats
        if isinstance(stats, list) and stats:
            return stats[0]
    return None
