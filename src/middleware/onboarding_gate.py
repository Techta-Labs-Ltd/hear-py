from __future__ import annotations

from typing import Any, Dict

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.context import RequestContext
from src.alexa.onboarding import Onboarding
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.constants.onboarding import OnboardingConstants
from src.services.logging_control import ApplicationLog


class OnboardingPolicy:
    _SKIP_INTENTS = frozenset(
        {"SkipFeedbackIntent", "AMAZON.NextIntent", "AMAZON.SkipIntent"}
    )
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
        if store.get("onboardingComplete") or any(
            store.get(field)
            for field in (
                "listenerId",
                "firstLaunchedAt",
                "launchCount",
                "lastToken",
                "userCity",
                "locality",
                "userName",
                "fullName",
                "userEmail",
                "listenerProfileResolvedAt",
            )
        ):
            return False
        return store.get("playCount", 0) == 0

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

    def __init__(
        self,
        *,
        user,
        onboarding,
        permission,
        town_capture,
        decline,
        finalize_town_skipped,
        handle_permission_no,
    ) -> None:
        self._user = user
        self._onboarding = onboarding
        self._permission = permission
        self._town_capture = town_capture
        self._decline = decline
        self._finalize_town_skipped = finalize_town_skipped
        self._handle_permission_no = handle_permission_no

    def can_handle(self, handler_input: HandlerInput) -> bool:
        rt = AlexaRequest.get_request_type(handler_input)
        if rt == "LaunchRequest":
            store = self._user.snapshot(handler_input)
            return OnboardingPolicy._is_new_user(store) and (
                not OnboardingPolicy._onboarding_completed_in_session(handler_input)
            )
        if isinstance(rt, str) and rt.startswith("AudioPlayer."):
            return False
        if rt == "SessionEndedRequest":
            return False
        if rt != "IntentRequest":
            return False
        store = self._user.snapshot(handler_input)
        intent = AlexaRequest.get_intent_name(handler_input)
        if store.get("awaitingProfilePermission") and intent in OnboardingPolicy._SKIP_INTENTS:
            return True
        if store.get("awaitingProfileSetupConsent"):
            return False
        if not OnboardingPolicy._is_new_user(
            store
        ) or OnboardingPolicy._onboarding_completed_in_session(handler_input):
            return False
        if intent in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
            return False
        if intent in {"SetUpAccountIntent", "SetLocationIntent", "SearchLocationIntent"}:
            return False
        stage = OnboardingPolicy._get_stage(handler_input, store)
        if stage and intent in OnboardingPolicy._SKIP_INTENTS:
            return True
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
            return Onboarding.ask_for_permission(
                handler_input, self._user.snapshot(handler_input), self._onboarding
            )
        intent = AlexaRequest.get_intent_name(handler_input)
        store = self._user.snapshot(handler_input)
        stage = OnboardingPolicy._get_stage(handler_input, store)
        if intent in OnboardingPolicy._SKIP_INTENTS:
            if store.get("awaitingProfilePermission"):
                return await self._decline.finalize_profile_skipped(
                    handler_input
                )
            return self._finalize_town_skipped(handler_input, store)
        if stage == OnboardingConstants.ONBOARDING_ASK_TOWN:
            attrs = RequestContext.request(handler_input) or {}
            nlp = attrs.get("_nlp") or {}
            slots = nlp.get("slots") or {}
            attempted_city = (
                slots.get("townName") or slots.get("placeName") or slots.get("residualQuery")
            )
            ApplicationLog.info(
                "Hear: city reply was not captured intent=%s attempted=%s; asking again",
                intent,
                bool(attempted_city),
            )
            return Onboarding.resume_town_capture(
                handler_input,
                store,
                self._onboarding,
                str(attempted_city).strip() if attempted_city else None,
            )
        if stage == OnboardingConstants.ONBOARDING_AWAIT_CONFIRM:
            redirect = OnboardingPolicy._confirm_echo(handler_input, store)
            if redirect is not None:
                return redirect
        if stage == "ask_permission" or not stage:
            if intent == "AMAZON.YesIntent":
                return await self._permission.complete_first_run(handler_input)
            if intent == "AMAZON.NoIntent":
                return self._handle_permission_no(handler_input, store)
            if intent in {"SkipFeedbackIntent", "AMAZON.CancelIntent"}:
                return self._finalize_town_skipped(handler_input, store)
            if intent in {
                "TownCaptureIntent",
                "SetLocationIntent",
                "SearchLocationIntent",
            }:
                self._onboarding.begin_town_capture(handler_input)
                return await self._town_capture.execute(handler_input)
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(
                    "Please say yes or no."
                )
            )
            .set_should_end_session(False)
            .response
        )
