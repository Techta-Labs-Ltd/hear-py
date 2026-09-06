from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.request import AlexaRequest
from src.alexa.search_speech import SearchSpeech
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.dialog import DialogSelection, DialogStateManager
from src.models.onboarding import Onboarding


class FallbackModule:
    logger = logging.getLogger(__name__)

    @staticmethod
    def source_name_response(handler_input, store: dict):
        active = DialogStateManager.active_from_store(store) or {}
        dialog_type = active.get("type")
        prompts = {
            "creator_name": (
                "Which creator would you like to hear?",
                "Just say their name.",
                "creatorQuery",
            ),
            "organization_name": (
                Speech.ASK_TALKING_NEWSPAPER,
                Speech.ASK_TALKING_NEWSPAPER_REPROMPT,
                "organizationQuery",
            ),
        }
        prompt = prompts.get(dialog_type)
        if not prompt:
            return None
        speech, reprompt, slot_name = prompt
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Ssml.ssml(reprompt))
            .add_directive({"type": "Dialog.ElicitSlot", "slotToElicit": slot_name})
            .set_should_end_session(False)
            .response
        )


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
        source_name_response = FallbackModule.source_name_response(handler_input, store)
        if source_name_response is not None:
            return source_name_response
        pending = store.get("pendingAmbiguity")
        if isinstance(pending, dict) and pending.get("candidates"):
            slots = pending.get("slots") or {}
            references = slots.get("ambiguousReferences") or []
            phrase = (
                references[0].get("phrase")
                if references and isinstance(references[0], dict)
                else "that name"
            )
            displayed = DialogSelection.displayed_choices(pending)
            has_more = DialogSelection.displayed_has_more(pending)
            has_previous = DialogSelection.displayed_has_previous(pending)
            message = SearchSpeech.ambiguous_reference_message(
                str(phrase or "that name"),
                displayed,
                has_more=has_more,
                has_previous=has_previous,
            )
            reprompt = SearchSpeech.choice_reprompt(
                displayed, has_more=has_more, has_previous=has_previous
            )
            return (
                handler_input.response_builder.speak(Ssml.ssml(message))
                .reprompt(Ssml.ssml(reprompt))
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
        source_name_response = FallbackModule.source_name_response(
            handler_input, self._deps.user.snapshot(handler_input)
        )
        if source_name_response is not None:
            return source_name_response
        return (
            handler_input.response_builder.speak(Speech.FALLBACK_SPEECH)
            .reprompt(Speech.WELCOME_REPROMPT)
            .set_should_end_session(False)
            .response
        )
