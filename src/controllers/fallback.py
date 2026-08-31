from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.request import AlexaRequest
from src.alexa.search_speech import SearchSpeech
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.onboarding import Onboarding


class FallbackModule:
    logger = logging.getLogger(__name__)


class FallbackHandler(AbstractRequestHandler):
    """Handles AMAZON.FallbackIntent — generic fallback speech."""

    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "AMAZON.FallbackIntent"
        )

    def handle(self, handler_input: HandlerInput):
        store = self._deps.user.snapshot(handler_input)
        pending = store.get("pendingAmbiguity")
        if isinstance(pending, dict) and pending.get("candidates"):
            slots = pending.get("slots") or {}
            references = slots.get("ambiguousReferences") or []
            phrase = (
                references[0].get("phrase")
                if references and isinstance(references[0], dict)
                else "that name"
            )
            message = SearchSpeech.ambiguous_reference_message(
                str(phrase or "that name"), list(pending.get("candidates") or [])[:3]
            )
            return (
                handler_input.response_builder.speak(Ssml.ssml(message))
                .reprompt(Ssml.ssml("Please say one of the names I just offered."))
                .set_should_end_session(False)
                .response
            )
        redirect = Onboarding.onboarding_pending_redirect(handler_input, store, deps=self._deps)
        if redirect is not None:
            return redirect
        return (
            handler_input.response_builder.speak(Speech.FALLBACK_SPEECH)
            .reprompt(Speech.WELCOME_REPROMPT)
            .set_should_end_session(False)
            .response
        )


class UnmatchedIntentHandler(AbstractRequestHandler):
    """Catch-all for unmatched IntentRequests."""

    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "IntentRequest"

    def handle(self, handler_input: HandlerInput):
        intent_name = AlexaRequest.get_intent_name(handler_input)
        dialog_state = None
        try:
            dialog_state = handler_input.request_envelope.request.dialogState
        except Exception:
            pass
        FallbackModule.logger.info(
            "Hear: unmatched IntentRequest intentName=%s dialogState=%s",
            intent_name,
            dialog_state,
        )
        redirect = Onboarding.onboarding_pending_redirect(
            handler_input, self._deps.user.snapshot(handler_input), deps=self._deps
        )
        if redirect is not None:
            return redirect
        return (
            handler_input.response_builder.speak(Speech.FALLBACK_SPEECH)
            .reprompt(Speech.WELCOME_REPROMPT)
            .set_should_end_session(False)
            .response
        )
