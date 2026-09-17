from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor

from src.alexa.dialog import DialogStateManager
from src.alexa.direct_intents import DirectIntentPolicy
from src.alexa.phrase_router import PhraseRoute, PhraseRouter
from src.alexa.request import AlexaRequest
from src.models.user import User
from src.services.logging_control import ApplicationLog


class DirectIntentPhraseInterceptor(AbstractRequestInterceptor):
    """Apply reusable phrase routing before the resolver can consume a request."""

    _SLOT_PRIORITY = ("searchQuery", "discoveryQuery", "topic", "category")

    @classmethod
    def _phrase(cls, intent) -> str | None:
        slots = AlexaRequest.read(intent, "slots") or {}
        for slot_name in cls._SLOT_PRIORITY:
            phrase = AlexaRequest.get_spoken_slot_value(AlexaRequest.read(slots, slot_name))
            if phrase:
                return phrase
        return None

    @staticmethod
    def _set(intent, route: PhraseRoute) -> None:
        slots = route.slot_map()
        if isinstance(intent, dict):
            intent["name"] = route.intent_name
            intent["slots"] = slots
            return
        setattr(intent, "name", route.intent_name)
        setattr(intent, "slots", slots)

    async def process(self, handler_input) -> None:
        if AlexaRequest.get_request_type(handler_input) != "IntentRequest":
            return
        request = AlexaRequest.read(handler_input.request_envelope, "request")
        intent = AlexaRequest.read(request, "intent")
        source_intent = AlexaRequest.read(intent, "name")
        if not intent:
            return
        store = User.snapshot(handler_input)
        active_dialog = DialogStateManager.active_from_store(store) or {}
        if (
            active_dialog.get("type") == "feedback"
            and store.get("awaitingFeedback")
            and source_intent == "ReportContentIntent"
        ):
            # Alexa supplies neither transcript nor confidence for this no-slot
            # intent. Keep a possible NLU mistake in the feedback dialog instead
            # of creating a false report.
            self._set(intent, PhraseRoute("FeedbackResponseIntent"))
            ApplicationLog.warning(
                "Hear: feedback dialog rerouted sourceIntent=%s targetIntent=%s",
                source_intent,
                "FeedbackResponseIntent",
            )
            return
        if source_intent not in DirectIntentPolicy.PHRASE_ROUTABLE_SEARCH_INTENTS:
            return
        phrase = self._phrase(intent)
        if active_dialog.get("type") == "help" and PhraseRouter.is_help_more(phrase):
            self._set(intent, PhraseRoute("AMAZON.NextIntent"))
            return
        if active_dialog or store.get("pendingAmbiguity"):
            route = PhraseRouter.control_route(
                phrase, allowed=PhraseRouter.INTERRUPT_CONTROL_INTENTS
            )
            if route:
                self._set(intent, route)
                ApplicationLog.info(
                    "Hear: active-dialog phrase route sourceIntent=%s targetIntent=%s",
                    source_intent,
                    route.intent_name,
                )
            return
        route = PhraseRouter.classify(phrase)
        if not route:
            return
        self._set(intent, route)
        ApplicationLog.info(
            "Hear: phrase route sourceIntent=%s targetIntent=%s",
            source_intent,
            route.intent_name,
        )
