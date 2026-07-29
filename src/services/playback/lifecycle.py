"""Compatibility facade over the single canonical active-playback owner."""
from __future__ import annotations

from src.services.playback.events import emit_listening_event
from src.services.playback.session import read_playback_session, write_playback_session
from src.services.storage.persistence import get_store


class PlaybackService:
    async def flush_previous(
        self,
        alexa_user_id: str,
        override_offset_ms: int | None = None,
        handler_input=None,
    ) -> dict | None:
        """Persist an unfinished item as paused; never create duplicate state."""
        del alexa_user_id
        if handler_input is None:
            return None
        state = read_playback_session(get_store(handler_input))
        if not state or state.get("status") not in {"starting", "playing", "paused"}:
            return None
        patch = {"status": "paused"}
        if override_offset_ms is not None:
            patch["offsetMs"] = max(0, int(override_offset_ms))
        state = write_playback_session(handler_input, patch)
        await emit_listening_event(handler_input, "paused", state)
        return state


playback_service = PlaybackService()


async def flush_previous_track(
    alexa_user_id: str,
    override_offset_ms: int | None = None,
    handler_input=None,
) -> dict | None:
    return await playback_service.flush_previous(
        alexa_user_id,
        override_offset_ms,
        handler_input,
    )
