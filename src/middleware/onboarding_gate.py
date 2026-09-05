from __future__ import annotations

import logging
from typing import Any, Dict

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.constants.onboarding import OnboardingConstants
from src.models.onboarding import Onboarding, TownCapture


class OnboardingPolicy:
    logger = logging.getLogger(__name__)
    _ASK_TOWN_OWNED_INTENTS = frozenset(
        {
            "TownCaptureIntent",
            "SetLocationIntent",
            "AMAZON.NoIntent",
            "SkipFeedbackIntent",
        }
    )
    _AWAIT_CONFIRM_OWNED_INTENTS = frozenset(
        {
            "AMAZON.YesIntent",
            "AMAZON.NoIntent",
            "TownCaptureIntent",
            "SetLocationIntent",
        }
    )
    _NLP_OWNED_INTENTS = frozenset({"town_capture", "location_set"})

    @staticmethod
    def _is_new_user(store: Dict[str, Any]) -> bool:
        """Check if the user is new (no completed onboarding, no prior playback)."""
        if store.get("onboardingComplete"):
            return False
        return store.get("playCount", 0) == 0 and (not store.get("lastToken"))

    @staticmethod
    def _onboarding_completed_in_session(handler_input: HandlerInput) -> bool:
        session = RequestContext.session(handler_input) or {}
        return bool(session.get("onboardingComplete"))

    @staticmethod
    def _get_stage(handler_input: HandlerInput, store: dict) -> str | None:
        """Resolve the current onboarding stage from store or session attributes."""
        stage = store.get("onboardingStage")
        if not stage:
            sess = RequestContext.session(handler_input) or {}
            stage = sess.get("onboardingStage")
        return stage or None

    @staticmethod
    def _confirm_echo(handler_input: HandlerInput, store: Dict[str, Any]):
        """Re-ask the location confirmation using the pending candidate city."""
        pending = store.get("pendingLocationConfirm") or {}
        city = pending.get("city")
        has_coordinates = (
            pending.get("latitude") is not None and pending.get("longitude") is not None
        )
        if not city and not has_coordinates:
            return None
        speech = (
            Speech.ONBOARDING_TOWN_CONFIRM(city)
            if city
            else Speech.ONBOARDING_DEVICE_LOCATION_CONFIRM
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Ssml.ssml(OnboardingConstants.TOWN_CONFIRM_REPROMPT))
            .set_should_end_session(False)
            .response
        )


class OnboardingGateHandler(AbstractRequestHandler):
    """Gate handler that routes new users through onboarding before any content handlers."""

    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        rt = AlexaRequest.get_request_type(handler_input)
        if rt == "LaunchRequest":
            store = self._deps.user.snapshot(handler_input)
            return OnboardingPolicy._is_new_user(store) and (
                not OnboardingPolicy._onboarding_completed_in_session(handler_input)
            )
        if isinstance(rt, str) and rt.startswith("AudioPlayer."):
            return False
        if rt == "SessionEndedRequest":
            return False
        if rt != "IntentRequest":
            return False
        store = self._deps.user.snapshot(handler_input)
        if not OnboardingPolicy._is_new_user(
            store
        ) or OnboardingPolicy._onboarding_completed_in_session(handler_input):
            return False
        intent = AlexaRequest.get_intent_name(handler_input)
        if intent in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
            return False
        stage = OnboardingPolicy._get_stage(handler_input, store)
        if stage in (
            OnboardingConstants.ONBOARDING_ASK_TOWN,
            OnboardingConstants.ONBOARDING_AWAIT_CONFIRM,
        ):
            attrs = RequestContext.request(handler_input)
            nlp = attrs.get("_nlp", {}) if attrs else {}
            if nlp.get("intent") in OnboardingPolicy._NLP_OWNED_INTENTS:
                return False
            owned = (
                OnboardingPolicy._ASK_TOWN_OWNED_INTENTS
                if stage == OnboardingConstants.ONBOARDING_ASK_TOWN
                else OnboardingPolicy._AWAIT_CONFIRM_OWNED_INTENTS
            )
            return intent not in owned
        return stage == "ask_permission" or not stage

    async def handle(self, handler_input: HandlerInput):
        rt = AlexaRequest.get_request_type(handler_input)
        if rt == "LaunchRequest":
            store = self._deps.user.snapshot(handler_input)
            OnboardingPolicy.logger.info("Hear: checking device address on onboarding launch")
            return await Onboarding.auto_detect_location_or_manual(
                handler_input, store, deps=self._deps
            )
        intent = AlexaRequest.get_intent_name(handler_input)
        store = self._deps.user.snapshot(handler_input)
        stage = OnboardingPolicy._get_stage(handler_input, store)
        if stage == OnboardingConstants.ONBOARDING_ASK_TOWN:
            attrs = RequestContext.request(handler_input) or {}
            nlp = attrs.get("_nlp") or {}
            slots = nlp.get("slots") or {}
            attempted_city = (
                slots.get("townName") or slots.get("placeName") or slots.get("residualQuery")
            )
            OnboardingPolicy.logger.info(
                "Hear: city reply was not captured intent=%s attempted=%s; asking again",
                intent,
                bool(attempted_city),
            )
            return Onboarding.resume_town_capture(
                handler_input,
                store,
                str(attempted_city).strip() if attempted_city else None,
                deps=self._deps,
            )
        if stage == OnboardingConstants.ONBOARDING_AWAIT_CONFIRM:
            redirect = OnboardingPolicy._confirm_echo(handler_input, store)
            if redirect is not None:
                return redirect
        if stage == "ask_permission" or not stage:
            if intent == "AMAZON.YesIntent":
                return self._deps.permission.start_location(handler_input)
            if intent == "AMAZON.NoIntent":
                return Onboarding.handle_permission_no(handler_input, store, deps=self._deps)
            if intent in {"SkipFeedbackIntent", "AMAZON.CancelIntent"}:
                return Onboarding.finalize_town_skipped(handler_input, store, deps=self._deps)
            if intent in {"TownCaptureIntent", "SetLocationIntent"}:
                self._deps.onboarding.begin_town_capture(handler_input)
                return await TownCapture(deps=self._deps).execute(handler_input)
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(
                    "Please say yes to use your device location, say your city, or say skip to continue as a guest."
                )
            )
            .set_should_end_session(False)
            .response
        )
