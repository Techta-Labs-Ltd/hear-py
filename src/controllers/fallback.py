from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.availability_speech import AvailabilitySpeech
from src.alexa.dialog import DialogSelection, DialogStateManager
from src.alexa.entities import AlexaEntities
from src.alexa.onboarding import Onboarding
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.search_speech import SearchSpeech
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.availability_data import AvailabilityData
from src.models.user import User
from src.services.logging_control import ApplicationLog


class FallbackModule:

    @staticmethod
    def fallback_response(
        handler_input: HandlerInput, user: User, onboarding: Onboarding
    ):
        store = user.snapshot(handler_input)
        active = DialogStateManager.get_active(handler_input) or {}
        if active.get("type") == "availability":
            context = dict(active.get("context") or {})
            displayed = AvailabilityData.displayed(context)
            if displayed:
                kind = str(context.get("kind") or "choice")
                has_more = AvailabilityData.has_more(context)
                has_previous = max(0, int(context.get("offset") or 0)) > 0
                DialogStateManager.activate(handler_input, "availability", context=context)
                builder = (
                    handler_input.response_builder.speak(
                        Ssml.ssml(
                            AvailabilitySpeech.choice_retry(
                                kind,
                                displayed,
                                has_more=has_more,
                                has_previous=has_previous,
                            )
                        )
                    )
                    .reprompt(
                        Ssml.ssml(
                            AvailabilitySpeech.choice_reprompt(
                                kind, len(displayed), has_more, has_previous
                            )
                        )
                    )
                    .set_should_end_session(False)
                )
                directive = AlexaEntities.build_ambiguity_dynamic_entities_directive(
                    displayed
                )
                if directive:
                    builder.add_directive(directive)
                return builder.response
        pending = store.get("pendingAmbiguity")
        if not pending:
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
        redirect = Onboarding.onboarding_pending_redirect(
            handler_input, store, onboarding
        )
        if redirect is not None:
            return redirect
        return AlexaResponse.present_idle_next(
            handler_input,
            Speech.FALLBACK_SPEECH,
            Speech.WELCOME_REPROMPT,
        )


class FallbackHandler(AbstractRequestHandler):
    """Handles AMAZON.FallbackIntent — generic fallback speech."""

    def __init__(self, user: User, onboarding: Onboarding) -> None:
        self._user = user
        self._onboarding = onboarding

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "AMAZON.FallbackIntent"
        )

    def handle(self, handler_input: HandlerInput):
        return FallbackModule.fallback_response(
            handler_input, self._user, self._onboarding
        )


class UnmatchedIntentHandler(AbstractRequestHandler):
    """Catch-all for unmatched IntentRequests."""

    def __init__(self, user: User, onboarding: Onboarding) -> None:
        self._user = user
        self._onboarding = onboarding

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
        return FallbackModule.fallback_response(
            handler_input, self._user, self._onboarding
        )

