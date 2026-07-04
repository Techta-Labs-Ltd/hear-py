from __future__ import annotations

from src.services.persistence import get_store, update_store
from src.services.playback_state_store import get_state, set_state, clear_state


def read_playback_session(store: dict) -> dict | None:
    """Read the current playback session tracking state."""
    session = store.get("playbackSession") if store else None
    if not isinstance(session, dict):
        return None
    if not session.get("trackId") or not session.get("sessionId"):
        return None
    return dict(session)


def write_playback_session(handler_input, fields: dict) -> dict | None:
    """Write fields to the playback session tracking state."""
    if not isinstance(fields, dict):
        return None
    store = get_store(handler_input)
    merged = dict(store.get("playbackSession") or {})
    merged.update(fields)
    update_store(handler_input, {"playbackSession": merged})
    return merged


def clear_playback_session(handler_input):
    """Clear the playback session tracking state."""
    update_store(handler_input, {"playbackSession": None})


async def resolve_playback_state(alexa_user_id: str | None, handler_input) -> dict:
    """Resolve the full playback state, preferring the state table over persistence."""
    if alexa_user_id:
        try:
            from_table = await get_state(alexa_user_id)
        except Exception:
            from_table = None
        if from_table and from_table.get("trackId") and from_table.get("sessionId"):
            return {"source": "playback_state_table", "state": from_table}
    store = get_store(handler_input) if handler_input else None
    from_persistence = read_playback_session(store) if store else None
    if from_persistence and from_persistence.get("trackId") and from_persistence.get("sessionId"):
        return {"source": "skill_persistence", "state": from_persistence}
    return {"source": "none", "state": None}


async def save_playback_state(alexa_user_id: str | None, handler_input, fields: dict):
    """Save playback state to both persistence and the state table."""
    if handler_input:
        write_playback_session(handler_input, fields)
    if alexa_user_id:
        try:
            await set_state(alexa_user_id, fields)
        except Exception:
            pass
    return fields


async def clear_all_playback_state(alexa_user_id: str | None, handler_input):
    """Clear all playback state from persistence and the state table."""
    if handler_input:
        clear_playback_session(handler_input)
    if alexa_user_id:
        try:
            await clear_state(alexa_user_id)
        except Exception:
            pass
