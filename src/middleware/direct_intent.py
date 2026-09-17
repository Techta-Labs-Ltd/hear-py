from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor

from src.alexa.dialog import DialogStateManager
from src.alexa.phrase_router import PhraseRoute, PhraseRouter
from src.alexa.request import AlexaRequest
from src.alexa.runtime import AlexaMetrics
from src.models.user import User
from src.services.logging_control import ApplicationLog


class DirectIntentPhraseInterceptor(AbstractRequestInterceptor):
    _SLOT_PRIORITY = (
        "searchQuery",
        "discoveryQuery",
        "organizationQuery",
        "creatorQuery",
        "publicationSourceQuery",
        "cityQuery",
        "query",
        "localQuery",
        "recommendationQuery",
        "topic",
        "category",
        "feedbackPhrase",
        "selection",
        "sourceKind",
        "location",
        "townName",
    )

    @classmethod
    def _slot_phrases(cls, intent) -> tuple[tuple[str, str], ...]:
        slots = AlexaRequest.read(intent, "slots") or {}
        phrases: list[tuple[str, str]] = []
        for slot_name in cls._SLOT_PRIORITY:
            phrase = AlexaRequest.get_spoken_slot_value(AlexaRequest.read(slots, slot_name))
            if phrase:
                phrases.append((slot_name, phrase))
        for slot_name, slot in slots.items():
            if slot_name in cls._SLOT_PRIORITY:
                continue
            phrase = AlexaRequest.get_spoken_slot_value(slot)
            if phrase:
                phrases.append((slot_name, phrase))
        unique: list[tuple[str, str]] = []
        seen = set()
        for slot_name, phrase in phrases:
            normalized = PhraseRouter.normalize(phrase)
            if normalized and normalized not in seen:
                unique.append((slot_name, phrase))
                seen.add(normalized)
        return tuple(unique)

    @staticmethod
    def _route(
        slot_phrases: tuple[tuple[str, str], ...],
        *,
        allowed_controls: frozenset[str] | None = None,
    ) -> tuple[PhraseRoute, str] | None:
        for slot_name, phrase in slot_phrases:
            route = (
                PhraseRouter.control_route(phrase, allowed=allowed_controls)
                if allowed_controls is not None
                else PhraseRouter.classify(phrase)
            )
            if route:
                return route, slot_name
        return None

    @staticmethod
    def _record_route(source_intent: str, route: PhraseRoute, slot_name: str) -> None:
        if source_intent != route.intent_name:
            AlexaMetrics.increment("IntentRouteOverride")
        metric = {
            "trending": "IntentRouteTrending",
            "recommendation": "IntentRouteRecommendation",
            "location_mutation": "IntentRouteLocationMutation",
            "notification": "IntentRouteNotification",
            "transport": "IntentRoutePlaybackControl",
            "playback_control": "IntentRoutePlaybackControl",
            "feedback": "IntentRouteFeedback",
            "social": "IntentRouteSocial",
            "report": "IntentRouteReport",
        }.get(route.family)
        if metric:
            AlexaMetrics.increment(metric)
        ApplicationLog.info(
            "Hear: phrase route sourceIntent=%s targetIntent=%s routeFamily=%s routeRule=%s slot=%s",
            source_intent,
            route.intent_name,
            route.family or "declared_sample",
            route.rule_name or "model_sample",
            slot_name,
        )

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
            self._set(intent, PhraseRoute("FeedbackResponseIntent"))
            ApplicationLog.warning(
                "Hear: feedback dialog rerouted sourceIntent=%s targetIntent=%s",
                source_intent,
                "FeedbackResponseIntent",
            )
            return
        slot_phrases = self._slot_phrases(intent)
        phrases = tuple(phrase for _, phrase in slot_phrases)
        if not phrases:
            AlexaMetrics.increment("IntentRouteNoText")
        if active_dialog.get("type") == "help" and any(
            PhraseRouter.is_help_more(phrase) for phrase in phrases
        ):
            self._set(intent, PhraseRoute("AMAZON.NextIntent"))
            return
        if active_dialog or store.get("pendingAmbiguity"):
            match = self._route(
                slot_phrases, allowed_controls=PhraseRouter.INTERRUPT_CONTROL_INTENTS
            )
            if match:
                route, slot_name = match
                self._set(intent, route)
                self._record_route(source_intent, route, slot_name)
            return
        match = self._route(slot_phrases)
        if not match:
            return
        route, slot_name = match
        self._set(intent, route)
        self._record_route(source_intent, route, slot_name)
