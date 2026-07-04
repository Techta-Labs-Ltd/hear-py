from __future__ import annotations

import time

from src.services.alexa_api_client import send_playback_events
from src.services.persistence import get_store, update_store
from src.utils.listen_tracker import PLAYBACK_EVENT_TYPES, close_listen_segment
from src.utils.playback_context import get_alexa_user_id
from src.utils.playback_event_builder import build_playback_event, resolve_playback_event_media, alexa_timestamp_from_request
from src.utils.playback_session import resolve_playback_state
from src.utils.playback_timing import resolve_playback_event_timing

# User-initiated playback event types sent to the audio analytics endpoint.
# NOTE: confirm these string values against the backend send_playback_events
# contract — the keys are fixed by the call sites, the values may need tweaking.
USER_PLAYBACK_EVENT_TYPES = {
    "USER_STOPPED": "USER_PLAYBACK_STOPPED",
    "PAUSED": "USER_PLAYBACK_PAUSED",
    "RESUMED": "USER_PLAYBACK_RESUMED",
    "CANCELLED": "USER_PLAYBACK_CANCELLED",
}


async def emit_user_playback_event(handler_input, *, event_type=None, event_label=None, suppress_following_stopped: bool = False, suppress_following_started: bool = False, close_segment: bool = False) -> bool:
    """Emit a user playback event to the Alexa audio analytics endpoint."""
    alexa_user_id = get_alexa_user_id(handler_input)
    if not alexa_user_id or not event_type:
        return False

    store = get_store(handler_input)
    result = await resolve_playback_state(alexa_user_id, handler_input)
    state = result.get("state")
    if not state or not state.get("trackId") or not state.get("sessionId"):
        return False

    position_ms = max(0, store.get("lastOffsetMs") or (state.get("lastKnownOffsetMs") or 0))
    if close_segment:
        close_listen_segment(handler_input, offset_ms=position_ms)

    timing = resolve_playback_event_timing(state, store, position_ms)
    media = resolve_playback_event_media(store, state)
    now = int(time.time() * 1000)
    alexa_ts = alexa_timestamp_from_request(getattr(getattr(handler_input, "request_envelope", None), "request", None) if hasattr(handler_input, "request_envelope") else None)

    await send_playback_events(alexa_user_id=alexa_user_id, events=[
        build_playback_event(
            session_id=state["sessionId"], track_id=state["trackId"],
            event_type=event_type, position_ms=position_ms,
            track_duration_ms=timing["trackDurationMs"],
            event_label=event_label or event_type, timestamp=now,
            alexa_timestamp=alexa_ts, **media,
        ),
    ], refresh_track_ids=[state["trackId"]], handler_input=handler_input)

    patch: dict = {}
    if suppress_following_stopped:
        patch["suppressNextStoppedEvent"] = True
    if suppress_following_started:
        patch["suppressNextStartedEvent"] = True
    if patch:
        update_store(handler_input, patch)

    return True


def consume_suppressed_playback_event(handler_input, kind: str) -> bool:
    """Check and consume a suppressed playback event flag."""
    store = get_store(handler_input)
    key = "suppressNextStartedEvent" if kind == "started" else "suppressNextStoppedEvent"
    if not store.get(key):
        return False
    update_store(handler_input, {key: False})
    return True
