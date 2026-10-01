from __future__ import annotations

from src.alexa.context import RequestContext


class FollowingSessionState:
    """Backend-synced follow snapshot plus current-session event overrides."""

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
        return {
            "id": source_id,
            "name": str(source.get("name") or "").strip() or None,
            "type": source_type,
        }

    @classmethod
    def _snapshot(cls, session: dict) -> list[dict] | None:
        if cls.SNAPSHOT_KEY not in session:
            return None
        values = session.get(cls.SNAPSHOT_KEY)
        sources = values if isinstance(values, list) else []
        normalized: list[dict] = []
        seen: set[str] = set()
        for source in sources:
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
    def _overrides(cls, session: dict) -> dict[str, dict]:
        raw = session.get(cls.SESSION_KEY)
        if not isinstance(raw, dict):
            return {}
        normalized: dict[str, dict] = {}
        for key, value in raw.items():
            if isinstance(value, bool):
                normalized[str(key)] = {"followed": value}
            elif isinstance(value, dict) and isinstance(value.get("followed"), bool):
                normalized[str(key)] = dict(value)
        return normalized

    @classmethod
    def _apply_overrides(cls, snapshot: list[dict], overrides: dict[str, dict]) -> list[dict]:
        by_key = {
            cls._key(item["id"], item["type"]): dict(item)
            for item in snapshot
        }
        for key, override in overrides.items():
            if override["followed"]:
                source = cls._normalize_source(override)
                if source:
                    by_key[key] = source
            else:
                by_key.pop(key, None)
        return list(by_key.values())

    @classmethod
    def replace_snapshot(cls, handler_input, sources: object) -> list[dict]:
        session = dict(RequestContext.session(handler_input) or {})
        values = sources if isinstance(sources, list) else []
        normalized = [
            item
            for source in values
            if (item := cls._normalize_source(source))
        ]
        deduped = list(
            {
                cls._key(item["id"], item["type"]): item
                for item in normalized
            }.values()
        )
        effective = cls._apply_overrides(deduped, cls._overrides(session))
        session[cls.SNAPSHOT_KEY] = effective
        RequestContext.replace_session(handler_input, session)
        return effective

    @classmethod
    def followed_sources(cls, handler_input) -> list[dict] | None:
        session = RequestContext.session(handler_input) or {}
        snapshot = cls._snapshot(session)
        if snapshot is None:
            return None
        return cls._apply_overrides(snapshot, cls._overrides(session))

    @classmethod
    def status(cls, handler_input, source_id: str, source_type: str) -> bool | None:
        session = RequestContext.session(handler_input) or {}
        key = cls._key(source_id, source_type)
        override = cls._overrides(session).get(key)
        if override is not None:
            return bool(override["followed"])
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
        overrides = cls._overrides(session)
        overrides[key] = {
            "id": str(source_id),
            "name": str(source_name or "").strip() or None,
            "type": source_type,
            "followed": bool(followed),
        }
        session[cls.SESSION_KEY] = overrides

        snapshot = cls._snapshot(session)
        if snapshot is not None:
            session[cls.SNAPSHOT_KEY] = cls._apply_overrides(snapshot, overrides)

        RequestContext.replace_session(handler_input, session)
