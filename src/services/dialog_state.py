"""Authoritative foreground conversation state with legacy compatibility."""
from __future__ import annotations

import time
from copy import deepcopy

from src.services.storage.store import get_store, update_store

DIALOG_TTL_SECONDS = 10 * 60

_LEGACY_FLAGS = {
    "search_confirmation": "awaitingSearchConfirmation",
    "feedback": "awaitingFeedback",
    "report_decision": "awaitingReportDecision",
    "resume": "awaitingResume",
    "notification_choice": "awaitingNotificationChoice",
}


def _now() -> int:
    return int(time.time())


def active_dialog_from_store(store: dict | None) -> dict | None:
    """Return the active dialog, deriving one from legacy state when needed."""
    state = store if isinstance(store, dict) else {}
    active = state.get("activeDialog")
    if isinstance(active, dict) and active.get("type"):
        expires_at = int(active.get("expiresAt") or 0)
        if not expires_at or expires_at >= _now():
            return active

    if state.get("awaitingSearchConfirmation") and state.get("pendingResolution"):
        return {"type": "search_confirmation", "context": deepcopy(state["pendingResolution"])}
    if state.get("pendingAmbiguity"):
        return {"type": "ambiguity", "context": deepcopy(state["pendingAmbiguity"])}
    if state.get("onboardingStage"):
        return {"type": "onboarding", "context": {"stage": state["onboardingStage"]}}
    if state.get("awaitingReportDecision"):
        return {"type": "report_decision", "context": deepcopy(state.get("reportContext") or {})}
    if state.get("awaitingFeedback"):
        return {"type": "feedback", "context": deepcopy(state.get("pendingFeedback") or {})}
    if state.get("awaitingResume"):
        return {"type": "resume", "context": deepcopy(state.get("activePlayback") or {})}
    if state.get("awaitingNotificationChoice"):
        return {"type": "notification_choice", "context": {}}
    return None


def get_active_dialog(handler_input) -> dict | None:
    return active_dialog_from_store(get_store(handler_input))


def activate_dialog(
    handler_input,
    dialog_type: str,
    *,
    context: dict | None = None,
    deferred_request: dict | None = None,
    ttl_seconds: int = DIALOG_TTL_SECONDS,
) -> dict:
    """Replace the foreground dialog and mirror its legacy flag for rollout."""
    now = _now()
    active = {
        "type": dialog_type,
        "context": deepcopy(context or {}),
        "deferredRequest": deepcopy(deferred_request) if deferred_request else None,
        "createdAt": now,
        "expiresAt": now + max(1, int(ttl_seconds)),
    }
    updates = {flag: False for flag in _LEGACY_FLAGS.values()}
    legacy_flag = _LEGACY_FLAGS.get(dialog_type)
    if legacy_flag:
        updates[legacy_flag] = True
    updates.update({"activeDialog": active, "_requiresReliableSave": True})
    return update_store(handler_input, updates)


def clear_active_dialog(handler_input, *dialog_types: str) -> dict:
    """Clear the dialog when it matches one of the supplied types."""
    store = get_store(handler_input)
    active = active_dialog_from_store(store)
    if dialog_types and (not active or active.get("type") not in dialog_types):
        return store
    updates = {"activeDialog": None}
    if active and active.get("type") in _LEGACY_FLAGS:
        updates[_LEGACY_FLAGS[active["type"]]] = False
    return update_store(handler_input, updates)


def migrate_active_dialog(store: dict) -> dict:
    """Materialize one valid active dialog from legacy persisted flags."""
    if not isinstance(store, dict):
        return store
    active = active_dialog_from_store({**store, "activeDialog": store.get("activeDialog")})
    store["activeDialog"] = deepcopy(active) if active else None
    return store
