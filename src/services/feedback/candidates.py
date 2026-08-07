from __future__ import annotations

import time

from src.services.storage.persistence import get_store, update_store
from src.services.dialog_state import activate_dialog


def _feedback_key(state: dict) -> str | None:
    return state.get("contentId")


def record_feedback_candidate(
    handler_input,
    state: dict,
    *,
    completed: bool,
) -> dict | None:
    """Record one meaningful, deduplicated feedback candidate."""
    if not completed:
        return None
    key = _feedback_key(state)
    listened_ms = max(0, int(state.get("listenedMs") or 0))
    if not key:
        return None
    store = get_store(handler_input)
    if key in (store.get("answeredFeedbackKeys") or []):
        return None
    candidate = {
        "feedbackKey": key,
        "contentId": state.get("contentId"),
        "publicationId": state.get("publicationId"),
        "title": state.get("title") or state.get("publicationTitle"),
        "publicationTitle": state.get("publicationTitle"),
        "creatorId": state.get("creatorId"),
        "creatorName": state.get("creatorName"),
        "category": state.get("category"),
        "listenedMs": listened_ms,
        "completed": bool(completed),
        "sessionId": state.get("sessionId"),
        "createdAt": int(time.time() * 1000),
    }
    existing = [
        value for value in (store.get("feedbackCandidates") or [])
        if value.get("feedbackKey") != key
    ]
    update_store(handler_input, {"feedbackCandidates": (existing + [candidate])[-20:]})
    return candidate


def activate_best_feedback_candidate(handler_input) -> dict | None:
    """Activate at most one candidate and discard the rest from its session."""
    store = get_store(handler_input)
    if store.get("awaitingFeedback"):
        return store.get("pendingFeedback")
    candidates = [
        item for item in (store.get("feedbackCandidates") or [])
        if item.get("completed") is True
        if item.get("feedbackKey") not in (store.get("answeredFeedbackKeys") or [])
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            bool(item.get("completed")),
            int(item.get("listenedMs") or 0),
            int(item.get("createdAt") or 0),
        ),
        reverse=True,
    )
    selected = candidates[0]
    session_id = selected.get("sessionId")
    remaining = [
        item for item in candidates
        if item.get("sessionId") != session_id
    ]
    update_store(handler_input, {
        "pendingFeedback": selected,
        "feedbackCandidates": remaining,
        "awaitingFeedback": True,
        "_requiresReliableSave": True,
    })
    activate_dialog(handler_input, "feedback", context=selected)
    return selected


def mark_pending_feedback_answered(handler_input) -> dict:
    store = get_store(handler_input)
    pending = store.get("pendingFeedback") or {}
    key = pending.get("feedbackKey")
    answered = list(store.get("answeredFeedbackKeys") or [])
    if key and key not in answered:
        answered.append(key)
    return update_store(handler_input, {
        "answeredFeedbackKeys": answered[-100:],
        "pendingFeedback": None,
        "awaitingFeedback": False,
        "activeDialog": None,
        "_requiresReliableSave": False,
    })


async def submit_feedback(handler_input, value: str) -> dict:
    """Close the pending prompt after an explicit feedback response."""
    del value
    return mark_pending_feedback_answered(handler_input)
