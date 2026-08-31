from __future__ import annotations

import time
from copy import deepcopy

from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.runtime import AttrDict
from src.constants.dialog import DialogConstants
from src.models.user import User


class DialogStateManager:
    __slots__ = ()

    @staticmethod
    def _now() -> int:
        return int(time.time())

    @staticmethod
    def active_from_store(store: dict | None) -> dict | None:
        return User.active_dialog(store)

    @staticmethod
    def get_active(handler_input) -> dict | None:
        return DialogStateManager.active_from_store(User.snapshot(handler_input))

    @staticmethod
    def activate(
        handler_input,
        dialog_type: str,
        *,
        context: dict | None = None,
        deferred_request: dict | None = None,
        ttl_seconds: int = DialogConstants.DIALOG_TTL_SECONDS,
    ) -> dict:
        now = DialogStateManager._now()
        active = {
            "type": dialog_type,
            "context": deepcopy(context or {}),
            "deferredRequest": deepcopy(deferred_request) if deferred_request else None,
            "createdAt": now,
            "expiresAt": now + max(1, int(ttl_seconds)),
        }
        updates = {flag: False for flag in DialogConstants.DIALOG_LEGACY_FLAGS.values()}
        legacy_flag = DialogConstants.DIALOG_LEGACY_FLAGS.get(dialog_type)
        if legacy_flag:
            updates[legacy_flag] = True
        updates.update({"activeDialog": active, "_requiresReliableSave": True})
        return User.update(handler_input, updates)

    @staticmethod
    def clear(handler_input, *dialog_types: str) -> dict:
        store = User.snapshot(handler_input)
        raw_active = store.get("activeDialog")
        active = (
            raw_active
            if isinstance(raw_active, dict) and raw_active.get("type")
            else DialogStateManager.active_from_store(store)
        )
        if dialog_types and (not active or active.get("type") not in dialog_types):
            return store
        updates = {"activeDialog": None}
        if active and active.get("type") in DialogConstants.DIALOG_LEGACY_FLAGS:
            updates[DialogConstants.DIALOG_LEGACY_FLAGS[active["type"]]] = False
        return User.update(handler_input, updates)

    @staticmethod
    def clear_transient_discovery(handler_input) -> dict:
        """Discard discovery choices that are only valid in the current session."""
        store = User.snapshot(handler_input)
        raw_active = store.get("activeDialog")
        active_type = raw_active.get("type") if isinstance(raw_active, dict) else None
        updates = {
            "awaitingSearchConfirmation": False,
            "pendingResolution": None,
            "pendingAmbiguity": None,
            "pendingSuggestions": [],
            "suggestionIndex": 0,
            "excludedSuggestions": [],
            "awaitingOrganizationName": False,
            "awaitingCreatorName": False,
            "_requiresReliableSave": True,
        }
        if active_type in DialogConstants.TRANSIENT_DISCOVERY_DIALOGS or (
            not active_type
            and (
                store.get("awaitingSearchConfirmation")
                or store.get("pendingResolution")
                or store.get("pendingAmbiguity")
            )
        ):
            updates["activeDialog"] = None
        return User.update(handler_input, updates)

    @staticmethod
    def dismiss_ambiguity(handler_input) -> dict:
        """Dismiss the current ambiguity without ending the Alexa session."""
        return User.update(
            handler_input,
            {
                "pendingAmbiguity": None,
                "activeDialog": None,
                "_requiresReliableSave": True,
            },
        )

    @staticmethod
    def migrate(store: dict) -> dict:
        return User.migrate_dialog(store)


class DeferredIntentManager:
    __slots__ = ()

    @staticmethod
    def _can_defer(handler_input) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input)
            in DialogConstants.DEFERRED_DISCOVERY_INTENTS
        )

    @staticmethod
    def capture(handler_input) -> bool:
        if not DeferredIntentManager._can_defer(handler_input):
            return False
        request = handler_input.request_envelope.request
        attrs = RequestContext.request(handler_input)
        deferred = {
            "intent": deepcopy(dict(request.intent)),
            "nlp": deepcopy((attrs or {}).get("_nlp") or {}),
            "pendingConfirmation": deepcopy((attrs or {}).get("_pendingConfirmation") or {}),
        }
        User.update(handler_input, {"deferredIntent": deferred})
        store = User.snapshot(handler_input)
        DialogStateManager.activate(
            handler_input,
            "feedback",
            context=store.get("pendingFeedback") or {},
            deferred_request=deferred,
        )
        return True

    @staticmethod
    def has(handler_input) -> bool:
        return isinstance(User.snapshot(handler_input).get("deferredIntent"), dict)

    @staticmethod
    async def resume(handler_input):
        deferred = User.snapshot(handler_input).get("deferredIntent")
        if not isinstance(deferred, dict) or not isinstance(deferred.get("intent"), dict):
            return None
        User.update(handler_input, {"deferredIntent": None})
        handler_input.request_envelope.request.intent = AttrDict(deferred["intent"])
        attrs = RequestContext.request(handler_input)
        attrs["_nlp"] = deepcopy(deferred.get("nlp") or {})
        pending = deferred.get("pendingConfirmation")
        if isinstance(pending, dict) and pending.get("resolution"):
            attrs["_pendingConfirmation"] = deepcopy(pending)
        RequestContext.replace_request(handler_input, attrs)
        DialogStateManager.clear(handler_input, "feedback", "report_decision")
        response = await handler_input.redispatch()
        speech = (response or {}).get("outputSpeech")
        if isinstance(speech, dict) and isinstance(speech.get("ssml"), str):
            speech["ssml"] = speech["ssml"].replace(
                "<speak>", "<speak>Thanks for the feedback. ", 1
            )
        return response
