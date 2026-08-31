from __future__ import annotations


class PlaybackContext:
    @staticmethod
    def read_audio_player_context(handler_input) -> dict | None:
        try:
            audio = handler_input.request_envelope.context.AudioPlayer
        except Exception:
            return None
        if not isinstance(audio, dict):
            return None
        token = str(audio["token"]) if audio.get("token") is not None else None
        offset = audio.get("offsetInMilliseconds")
        offset_ms = max(0, round(offset)) if isinstance(offset, (int, float)) else 0
        activity = audio.get("playerActivity")
        player_activity = str(activity) if activity is not None else None
        if not token and (not player_activity) and (offset_ms == 0):
            return None
        return {
            "token": token,
            "offsetMs": offset_ms,
            "playerActivity": player_activity,
        }

    @staticmethod
    def is_audio_player_active(context: dict | None) -> bool:
        if not context:
            return False
        if not context.get("playerActivity"):
            return bool(context.get("token"))
        return context["playerActivity"] in {"PLAYING", "PAUSED", "BUFFER_UNDERRUN"}
