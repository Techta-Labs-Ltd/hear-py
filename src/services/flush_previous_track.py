from __future__ import annotations
import time
from src.utils.playback_session import resolve_playback_state, clear_all_playback_state
from src.utils.playback_event_builder import build_playback_event, resolve_playback_event_media
from src.utils.playback_timing import resolve_playback_event_timing, resolve_flush_position_ms
from src.services.persistence import get_store
from src.services.alexa_api_client import send_playback_events


async def flush_previous_track(
    alexa_user_id: str,
    override_offset_ms: int | None = None,
    handler_input=None,
) -> dict | None:
    """Flush a STOPPED event for the previously playing track and clear state.

    Returns refreshed playback stats if the API call succeeded, or None.
    """
    try:
        result = await resolve_playback_state(alexa_user_id, handler_input)
        state = result.get("state")
        if not state or not state.get("trackId") or not state.get("sessionId"):
            return None

        position_ms = resolve_flush_position_ms(state, override_offset_ms)

        store = None
        if handler_input is not None and hasattr(handler_input, "attributes_manager"):
            try:
                store = get_store(handler_input)
            except Exception:
                pass

        timing = resolve_playback_event_timing(state, store, position_ms)
        media = resolve_playback_event_media(store, state)
        event_timestamp = int(time.time() * 1000)

        events = [
            build_playback_event(
                track_id=str(state["trackId"]),
                session_id=str(state["sessionId"]),
                event_type="AUDIO_PLAYER_PLAYBACK_STOPPED",
                position_ms=position_ms,
                track_duration_ms=timing["trackDurationMs"],
                event_label="STOPPED",
                timestamp=event_timestamp,
                **media,
            )
        ]

        refreshed_stats = None
        try:
            api_result = await send_playback_events(
                alexa_user_id=alexa_user_id,
                events=events,
                refresh_track_ids=[state["trackId"]],
                handler_input=handler_input,
            )
            refreshed_stats = (api_result or {}).get("refreshedStats") or None
        except Exception:
            pass

        await clear_all_playback_state(alexa_user_id, handler_input)
        return refreshed_stats
    except Exception:
        return None
