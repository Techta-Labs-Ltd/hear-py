from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler, AbstractRequestInterceptor

from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.ssml import Ssml
from src.constants.dialog import DialogConstants
from src.models.confirmation import ConfirmationPolicy


class ConfirmationMiddleware(AbstractRequestInterceptor):
    def process(self, handler_input) -> None:
        ConfirmationPolicy.apply(handler_input)


class SearchConfirmationGateHandler(AbstractRequestHandler):
    def can_handle(self, handler_input) -> bool:
        intent = AlexaRequest.get_intent_name(handler_input)
        if (
            AlexaRequest.get_request_type(handler_input) != "IntentRequest"
            or intent not in ConfirmationPolicy.ALEXA_INTENTS
        ):
            return False
        attrs = RequestContext.request(handler_input)
        if attrs.get(DialogConstants.VALIDATION_FAILURE):
            return False
        nlp = attrs.get("_nlp")
        if not isinstance(nlp, dict) or not nlp.get("intent"):
            return True
        slots = nlp.get("slots") or {}
        blocked = bool(
            nlp.get("intent") in {"unclear", "resolver_unavailable"}
            or (nlp.get("status") and nlp.get("status") != "resolved")
            or ConfirmationPolicy.has_pending_ambiguity(nlp)
            or nlp.get("directDiscoveryRequest")
            or slots.get("genericCreatorRequest")
            or slots.get("genericOrganizationRequest")
        )
        return bool(
            not blocked
            and nlp.get("intent") in ConfirmationPolicy.RESOLVED_INTENTS
            and not attrs.get("_pendingConfirmation")
            and not attrs.get("_resolverClarification")
        )

    def handle(self, handler_input):
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(
                    "I couldn't safely confirm that search. Please say what you'd like to hear again."
                )
            )
            .reprompt(Ssml.ssml("Name a topic, creator, publication, or talking newspaper."))
            .set_should_end_session(False)
            .response
        )
