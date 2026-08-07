from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from src.services.store import get_store
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import (
    ssml,
    WELCOME_REPROMPT,
    FALLBACK_SPEECH,
    ambiguous_reference_message,
)
from src.handlers.onboarding import onboarding_pending_redirect
class FallbackHandler(AbstractRequestHandler):
    """Handles AMAZON.FallbackIntent — generic fallback speech."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "AMAZON.FallbackIntent"
        )

    def handle(self, handler_input: HandlerInput):
        store = get_store(handler_input)
        pending = store.get("pendingAmbiguity")
        if isinstance(pending, dict) and pending.get("candidates"):
            slots = pending.get("slots") or {}
            references = slots.get("ambiguousReferences") or []
            phrase = (
                references[0].get("phrase")
                if references and isinstance(references[0], dict)
                else "that name"
            )
            message = ambiguous_reference_message(
                str(phrase or "that name"),
                list(pending.get("candidates") or [])[:3],
            )
            return handler_input.response_builder \
                .speak(ssml(message)) \
                .reprompt(ssml("Please say one of the names I just offered.")) \
                .set_should_end_session(False) \
                .response
        redirect = onboarding_pending_redirect(handler_input, store)
        if redirect is not None:
            return redirect
        return handler_input.response_builder \
            .speak(FALLBACK_SPEECH) \
            .reprompt(WELCOME_REPROMPT) \
            .set_should_end_session(False) \
            .response


class UnmatchedIntentHandler(AbstractRequestHandler):
    """Catch-all for unmatched IntentRequests."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return get_request_type(handler_input) == "IntentRequest"

    def handle(self, handler_input: HandlerInput):
        intent_name = get_intent_name(handler_input)
        dialog_state = None
        try:
            dialog_state = handler_input.request_envelope.request.dialogState
        except Exception:
            pass
        logger.info("Hear: unmatched IntentRequest intentName=%s dialogState=%s",
                     intent_name, dialog_state)
        redirect = onboarding_pending_redirect(handler_input, get_store(handler_input))
        if redirect is not None:
            return redirect
        return handler_input.response_builder \
            .speak(FALLBACK_SPEECH) \
            .reprompt(WELCOME_REPROMPT) \
            .set_should_end_session(False) \
            .response
