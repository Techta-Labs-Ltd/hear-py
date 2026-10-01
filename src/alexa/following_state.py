from __future__ import annotations

from src.alexa.context import RequestContext


class FollowingSessionState:
    """Backend-synced follow snapshot plus request-session command overrides."""

    SESSION_KEY = "followingCommandOverrides"
    SNAPSHOT_KEY = "followedCreators"

    @staticmethod
    def _key(source_id: str, source_type: str) -> str:
        return f"{source_type}:{source_id}"

    @classmethod
    def _normalize_source(cls, source: object) -> dict | None:
        if not isinstance(source, dict):
            return None
        source_id = str(source.get("id") or "").strip()
        source_type = str(source.get("type") or "creator").strip().casefold()
        if not source_id or source_type not in {"creator", "organization"}:
            return None
        name = str(source.get("name") or "").strip() or None
        return {"id": source_id, "name": name, "type": source_type}

    @classmethod
    def _snapshot(cls, session: dict) -> list[dict] | None:
        if cls.SNAPSHOT_KEY not in session:
            return None
        raw = session.get(cls.SNAPSHOT_KEY)
        values = raw if isinstance(raw, list) else []
        normalized: list[dict] = []
        seen: set[str] = set()
        for source in values:
            item = cls._normalize_source(source)
            if not item:
                continue
            key = cls._key(item["id"], item["type"])
            if key in seen:
                continue
            seen.add(key)
            normalized.append(item)
        return normalized

    @classmethod
    def replace_snapshot(cls, handler_input, sources: object) -> list[dict]:
        values = sources if isinstance(sources, list) else []
        normalized: list[dict] = []
        seen: set[str] = set()
        for source in values:
            item = cls._normalize_source(source)
            if not item:
                continue
            key = cls._key(item["id"], item["type"])
            if key in seen:
                continue
            seen.add(key)
            normalized.append(item)
        session = dict(RequestContext.session(handler_input) or {})
        session[cls.SNAPSHOT_KEY] = normalized
        session.pop(cls.SESSION_KEY, None)
        RequestContext.replace_session(handler_input, session)
        return normalized

    @classmethod
    def followed_sources(cls, handler_input) -> list[dict] | None:
        session = RequestContext.session(handler_input) or {}
        snapshot = cls._snapshot(session)
        if snapshot is None:
            return None
        return snapshot

    @classmethod
    def status(cls, handler_input, source_id: str, source_type: str) -> bool | None:
        session = RequestContext.session(handler_input) or {}
        key = cls._key(source_id, source_type)
        overrides = session.get(cls.SESSION_KEY)
        if isinstance(overrides, dict):
            value = overrides.get(key)
            if isinstance(value, bool):
                return value
        snapshot = cls._snapshot(session)
        if snapshot is None:
            return None
        return any(
            cls._key(item["id"], item["type"]) == key
            for item in snapshot
        )

    @classmethod
    def record(
        cls,
        handler_input,
        *,
        source_id: str,
        source_type: str,
        followed: bool,
        source_name: str | None = None,
    ) -> None:
        session = dict(RequestContext.session(handler_input) or {})
        key = cls._key(source_id, source_type)
        raw_overrides = session.get(cls.SESSION_KEY)
        overrides = dict(raw_overrides) if isinstance(raw_overrides, dict) else {}
        overrides[key] = bool(followed)
        session[cls.SESSION_KEY] = overrides

        snapshot = cls._snapshot(session)
        if snapshot is not None:
            by_key = {
                cls._key(item["id"], item["type"]): item
                for item in snapshot
            }
            if followed:
                by_key[key] = {
                    "id": str(source_id),
                    "name": str(source_name or "").strip() or None,
                    "type": source_type,
                }
            else:
                by_key.pop(key, None)
            session[cls.SNAPSHOT_KEY] = list(by_key.values())

        RequestContext.replace_session(handler_input, session)
