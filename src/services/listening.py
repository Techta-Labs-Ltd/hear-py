from __future__ import annotations
from src.services.store import get_store, update_store
from src.utils.normalize_content_item import is_bad_credit_name, is_id_like_label


class ListeningTracker:
    __slots__ = ()

    @staticmethod
    def _normalize_creator(store: dict, creator) -> str | None:
        if not creator:
            return None
        raw = str(creator).strip()
        if not raw:
            return None
        if not is_bad_credit_name(raw) and not is_id_like_label(raw):
            return raw
        creator_id = store.get("feedbackCreatorId") or store.get("currentCreatorId") or None
        if creator_id and str(creator_id) == raw:
            name = store.get("feedbackCreator") or store.get("currentCreator") or None
            if name and not is_bad_credit_name(name) and not is_id_like_label(name):
                return str(name).strip()
        for c in store.get("followedCreators") or []:
            if c.get("id") == raw:
                nm = c.get("name")
                if nm and not is_bad_credit_name(nm):
                    return str(nm).strip()
        return None

    @staticmethod
    def record(
        handler_input,
        *,
        category: str | None = None,
        creator: str | None = None,
        liked: bool | None = None,
    ) -> dict:
        store = get_store(handler_input)
        pattern = dict(store.get("listeningPattern") or {})
        score = 2 if liked is True else (-1 if liked is False else 1)
        if category:
            key = f"category:{category}"
            pattern[key] = (pattern.get(key) or 0) + score
        creator_label = ListeningTracker._normalize_creator(store, creator)
        if creator_label:
            key = f"creator:{creator_label}"
            pattern[key] = (pattern.get(key) or 0) + score
        return update_store(handler_input, {"listeningPattern": pattern})


_tracker = ListeningTracker()
record_listening_event = _tracker.record
