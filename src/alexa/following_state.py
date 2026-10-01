from __future__ import annotations

from src.alexa.context import RequestContext


class FollowingSessionState:
    """Session-only knowledge of follow commands issued during this Alexa session."""

    SESSION_KEY = "followingCommandOverrides"

    @staticmethod
    def _key(source_id: str, source_type: str) -> str:
        return f"{source_type}:{source_id}"

    @classmethod
    def status(cls, handler_input, source_id: str, source_type: str) -> bool | None:
        session = RequestContext.session(handler_input) or {}
        overrides = session.get(cls.SESSION_KEY)
        if not isinstance(overrides, dict):
            return None
        value = overrides.get(cls._key(source_id, source_type))
        return value if isinstance(value, bool) else None

    @classmethod
    def record(
        cls,
        handler_input,
        *,
        source_id: str,
        source_type: str,
        followed: bool,
    ) -> None:
        session = dict(RequestContext.session(handler_input) or {})
        raw = session.get(cls.SESSION_KEY)
        overrides = dict(raw) if isinstance(raw, dict) else {}
        overrides[cls._key(source_id, source_type)] = bool(followed)
        session[cls.SESSION_KEY] = overrides
        RequestContext.replace_session(handler_input, session)
