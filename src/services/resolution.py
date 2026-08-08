from __future__ import annotations
import time
import uuid

from src.utils.search_payload import normalize_search_payload


class ResolutionBuilder:
    __slots__ = ()

    @staticmethod
    def build(
        nlp: dict,
        confirmation_label: str,
        *,
        now: int | None = None,
    ) -> dict:
        timestamp = int(time.time()) if now is None else int(now)
        slots = nlp.get("slots") or {}
        payload = nlp.get("searchPayload") or slots.get("searchPlan") or {}
        return {
            "requestId": nlp.get("requestId") or str(uuid.uuid4()),
            "originalUtterance": nlp.get("originalUtterance") or "",
            "normalizedUtterance": nlp.get("normalizedUtterance") or "",
            "corrections": list(nlp.get("corrections") or []),
            "intent": nlp.get("intent") or "general",
            "confirmationLabel": confirmation_label,
            "searchPayload": normalize_search_payload(payload),
            "resolvedEntities": list(nlp.get("entities") or []),
            "alternatives": list(nlp.get("alternatives") or []),
            "createdAt": timestamp,
            "expiresAt": timestamp + 300,
        }


_resolution = ResolutionBuilder()
build_pending_resolution = _resolution.build
