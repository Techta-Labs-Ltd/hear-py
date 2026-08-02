from __future__ import annotations

from copy import deepcopy

from src.runtime import AttrDict
from src.services.storage.persistence import get_store, update_store
from src.services.dialog_state import clear_active_dialog
from src.services.dialog_state import activate_dialog
from src.utils.skill_request import get_intent_name, get_request_type

DISCOVERY_INTENTS = {
    "PlayContentIntent",
    "PlayLocalIntent",
    "PlayRecommendationIntent",
    "PlayByOrganizationIntent",
    "PlayByCreatorIntent",
    "PlayPublicationIntent",
    "BrowseContentIntent",
    "WhatsTrendingIntent",
}


def can_defer_current_intent(handler_input) -> bool:
    return (
        get_request_type(handler_input) == "IntentRequest"
        and get_intent_name(handler_input) in DISCOVERY_INTENTS
    )


def capture_deferred_intent(handler_input) -> bool:
    """Persist one content request while foreground feedback is collected."""
    if not can_defer_current_intent(handler_input):
        return False
    request = handler_input.request_envelope.request
    attrs = handler_input.attributes_manager.get_request_attributes()
    deferred = {
            "intent": deepcopy(dict(request.intent)),
            "nlp": deepcopy((attrs or {}).get("_nlp") or {}),
            "pendingConfirmation": deepcopy(
                (attrs or {}).get("_pendingConfirmation") or {}
            ),
    }
    update_store(handler_input, {"deferredIntent": deferred})
    store = get_store(handler_input)
    activate_dialog(
        handler_input,
        "feedback",
        context=store.get("pendingFeedback") or {},
        deferred_request=deferred,
    )
    return True


def has_deferred_intent(handler_input) -> bool:
    return isinstance(get_store(handler_input).get("deferredIntent"), dict)


async def resume_deferred_intent(handler_input):
    """Restore and dispatch the request that was paused by the feedback gate."""
    deferred = get_store(handler_input).get("deferredIntent")
    if not isinstance(deferred, dict) or not isinstance(deferred.get("intent"), dict):
        return None
    update_store(handler_input, {"deferredIntent": None})
    handler_input.request_envelope.request.intent = AttrDict(deferred["intent"])
    attrs = handler_input.attributes_manager.get_request_attributes()
    attrs["_nlp"] = deepcopy(deferred.get("nlp") or {})
    pending = deferred.get("pendingConfirmation")
    if isinstance(pending, dict) and pending.get("resolution"):
        attrs["_pendingConfirmation"] = deepcopy(pending)
    handler_input.attributes_manager.set_request_attributes(attrs)
    clear_active_dialog(handler_input, "feedback", "report_decision")
    response = await handler_input.redispatch()
    speech = (response or {}).get("outputSpeech")
    if isinstance(speech, dict) and isinstance(speech.get("ssml"), str):
        speech["ssml"] = speech["ssml"].replace(
            "<speak>",
            "<speak>Thanks for the feedback. ",
            1,
        )
    return response
