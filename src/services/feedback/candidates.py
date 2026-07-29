from __future__ import annotations

import time

from config import settings
from src.services.storage.persistence import get_store, update_store
from src.utils.skill_request import get_user_id
from src.webhooks.dispatch import dispatch


def _feedback_key(state: dict) -> str | None:
    return state.get("publicationId") or state.get("contentId")


def record_feedback_candidate(
    handler_input,
    state: dict,
    *,
    completed: bool,
) -> dict | None:
    """Record one meaningful, deduplicated feedback candidate."""
    key = _feedback_key(state)
    listened_ms = max(0, int(state.get("listenedMs") or 0))
    meaningful = completed or listened_ms >= settings.feedback_trigger_ms
    if not key or not meaningful:
        return None
    store = get_store(handler_input)
    if key in (store.get("answeredFeedbackKeys") or []):
        return None
    candidate = {
        "feedbackKey": key,
        "contentId": state.get("contentId"),
        "publicationId": state.get("publicationId"),
        "title": state.get("publicationTitle") or state.get("title"),
        "creatorId": state.get("creatorId"),
        "creatorName": state.get("creatorName"),
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
        "_requiresReliableSave": False,
    })


async def submit_feedback(handler_input, value: str) -> dict:
    """Dispatch one explicit feedback response and close the pending prompt."""
    store = get_store(handler_input)
    pending = store.get("pendingFeedback") or {}
    if pending.get("feedbackKey"):
        dispatch("feedback.given", {
            "alexaUserId": get_user_id(handler_input),
            "feedbackKey": pending.get("feedbackKey"),
            "contentId": pending.get("contentId"),
            "publicationId": pending.get("publicationId"),
            "creatorId": pending.get("creatorId"),
            "listenedMs": pending.get("listenedMs"),
            "feedback": value,
            "timestamp": int(time.time() * 1000),
        })
    return mark_pending_feedback_answered(handler_input)
