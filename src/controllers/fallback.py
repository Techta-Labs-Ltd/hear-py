from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.availability_speech import AvailabilitySpeech
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.search_speech import SearchSpeech
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.dialog import DialogSelection, DialogStateManager
from src.models.onboarding import Onboarding
from src.services.logging_control import ApplicationLog


class FallbackModule:

    @staticmethod
    def fallback_response(handler_input: HandlerInput, deps: object | None):
        store = deps.user.snapshot(handler_input) if deps and hasattr(deps, "user") else {}
        pending = store.get("pendingAmbiguity")
        if not pending:
            active = DialogStateManager.get_active(handler_input) or {}
            if active.get("type") == "ambiguity":
                pending = active.get("context")
        if isinstance(pending, dict) and pending.get("candidates"):
            displayed = DialogSelection.displayed_choices(pending)
            has_more = DialogSelection.displayed_has_more(pending)
            has_previous = DialogSelection.displayed_has_previous(pending)
            pagination = pending.get("candidatePagination") or {}
            publication_picker = pagination.get("kind") == "publication"
            message = (
                AvailabilitySpeech.choice_retry(
                    "publication",
                    displayed,
                    has_more=has_more,
                    has_previous=has_previous,
                )
                if publication_picker
                else SearchSpeech.ambiguity_retry_message(
                    displayed,
                    has_more=has_more,
                    has_previous=has_previous,
                )
            )
            reprompt = SearchSpeech.choice_reprompt(
                displayed,
                publication_picker=publication_picker,
                has_more=has_more,
                has_previous=has_previous,
            )
            return (
                handler_input.response_builder.speak(Ssml.ssml(message))
                .reprompt(Ssml.ssml(reprompt))
                .set_should_end_session(False)
                .response
            )
        redirect = Onboarding.onboarding_pending_redirect(handler_input, store, deps=deps)
        if redirect is not None:
            return redirect
        return AlexaResponse.present_idle_next(
            handler_input,
            Speech.FALLBACK_SPEECH,
            Speech.WELCOME_REPROMPT,
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
        return FallbackModule.fallback_response(handler_input, self._deps)


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
        ApplicationLog.info(
            "Hear: unmatched IntentRequest intentName=%s dialogState=%s",
            intent_name,
            dialog_state,
        )
        return FallbackModule.fallback_response(handler_input, self._deps)

