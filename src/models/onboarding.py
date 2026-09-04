from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ask_sdk_core.handler_input import HandlerInput

from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.constants.onboarding import OnboardingConstants
from src.models.dialog import DialogStateManager
from src.models.onboarding_state import OnboardingService, OnboardingState
from src.models.resolver import ResolverUnavailable
from src.models.user import User
from src.utils.content import ContentUtils
from src.utils.deadline import DeadlineBudget
from src.utils.filters import SearchFilterUtils


class LaunchTracker:
    __slots__ = ()

    @staticmethod
    def record(user_id: str, store: dict) -> dict:
        launches = (store.get("launchCount") or 0) + 1
        now = int(time.time() * 1000)
        first_launched_at = store.get("firstLaunchedAt") or now
        return {
            "isFirstTime": launches == 1,
            "isReturning": launches > 1,
            "launchCount": launches,
            "firstLaunchedAt": first_launched_at,
            "lastLaunchedAt": now,
            "save": {
                "launchCount": launches,
                "firstLaunchedAt": first_launched_at,
                "lastLaunchedAt": now,
            },
        }


class TownCapture:
    __slots__ = ("_deps",)

    def __init__(self, *, deps: object | None = None) -> None:
        self._deps = Onboarding._dependencies(deps)

    async def execute(self, handler_input: HandlerInput):
        store = self._deps.user.snapshot(handler_input)
        intent_name = AlexaRequest.get_intent_name(handler_input)
        if intent_name in (
            "AMAZON.NoIntent",
            "SkipFeedbackIntent",
            "AMAZON.CancelIntent",
        ):
            return Onboarding.finalize_town_skipped(handler_input, store, deps=self._deps)
        attrs = RequestContext.request(handler_input)
        nlp = attrs.get("_nlp", {}) if attrs else {}
        nlp_slots = nlp.get("slots", {}) if nlp else {}
        town = nlp_slots.get("townName") or nlp_slots.get("placeName")
        if not town:
            town = (
                AlexaRequest.get_slot_value(handler_input, "townName")
                or AlexaRequest.get_slot_value(handler_input, "city")
                or AlexaRequest.get_slot_value(handler_input, "location")
            )
        if town:
            return await Onboarding.stage_town_confirmation(
                handler_input, store, town, deps=self._deps
            )
        return Onboarding.resume_town_capture(handler_input, store, deps=self._deps)


class SetLocation:
    __slots__ = ("_deps",)

    def __init__(self, *, deps: object | None = None) -> None:
        self._deps = Onboarding._dependencies(deps)

    async def execute(self, handler_input: HandlerInput):
        attrs = RequestContext.request(handler_input)
        nlp = attrs.get("_nlp", {}) if attrs else {}
        town = (nlp.get("slots", {}) or {}).get("townName")
        if town:
            return await Onboarding.stage_town_confirmation(
                handler_input,
                self._deps.user.snapshot(handler_input),
                town,
                deps=self._deps,
            )
        self._deps.onboarding.request_location_change(handler_input)
        return (
            handler_input.response_builder.speak(Ssml.ssml("Sure. Which city are you in now?"))
            .reprompt(Ssml.ssml("Which city should I set as your location?"))
            .set_should_end_session(False)
            .response
        )


class Onboarding(OnboardingService):
    logger = logging.getLogger(__name__)

    def __init__(self, store: User | None = None) -> None:
        super().__init__(OnboardingState(store or User()))

    @staticmethod
    def _dependencies(deps: object | None):
        if deps is None:
            raise RuntimeError("Onboarding requires injected dependencies")
        return deps

    @staticmethod
    def _town_retry_response(handler_input: HandlerInput, speech: str, reprompt: str):
        """Keep Alexa's active location intent open so a bare town fills its slot."""
        builder = handler_input.response_builder.speak(Ssml.ssml(speech)).reprompt(
            Ssml.ssml(reprompt)
        )
        slot_name = {
            "TownCaptureIntent": "townName",
            "SetLocationIntent": "location",
        }.get(AlexaRequest.get_intent_name(handler_input))
        if slot_name:
            builder = builder.add_directive(
                {"type": "Dialog.ElicitSlot", "slotToElicit": slot_name}
            )
        return builder.set_should_end_session(False).response

    @staticmethod
    def onboarding_pending_redirect(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        *,
        deps: object | None = None,
    ):
        stage = store.get("onboardingStage")
        if stage == OnboardingConstants.ONBOARDING_ASK_TOWN:
            return Onboarding.resume_town_capture(handler_input, store, deps=deps)
        if stage == OnboardingConstants.ONBOARDING_AWAIT_CONFIRM:
            pending = store.get("pendingLocationConfirm") or {}
            city = pending.get("city")
            has_coordinates = (
                pending.get("latitude") is not None
                and pending.get("longitude") is not None
            )
            if not city and not has_coordinates:
                return None
            speech = (
                Speech.ONBOARDING_TOWN_CONFIRM(city)
                if city
                else Speech.ONBOARDING_DEVICE_LOCATION_CONFIRM
            )
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(speech)
                )
                .reprompt(Ssml.ssml(OnboardingConstants.TOWN_CONFIRM_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        return None

    @staticmethod
    def ask_for_permission(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        *,
        deps: object | None = None,
    ):
        """Prompt the user to grant location permission."""
        d = Onboarding._dependencies(deps)
        d.onboarding.ask_permission(handler_input)
        DialogStateManager.activate(
            handler_input, "onboarding", context={"stage": "ask_permission"}
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.ONBOARDING_ASK_PERMISSION))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def handle_permission_yes(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        *,
        deps: object | None = None,
    ):
        """Send the Alexa-owned consent card for the location data we consume."""
        permissions = [OnboardingConstants.PERMISSIONS["GEOLOCATION"]]
        d = Onboarding._dependencies(deps)
        d.onboarding.keep_permission_pending(handler_input)
        DialogStateManager.activate(
            handler_input, "onboarding", context={"stage": "ask_permission"}
        )
        Onboarding.logger.info(
            "Hear: permission card requested scopes=%s requestId=%s cardPresent=true",
            permissions,
            Onboarding._request_id(handler_input),
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.ONBOARDING_CONSENT_CARD_SENT))
            .with_ask_for_permissions_consent_card(permissions)
            .set_should_end_session(True)
            .response
        )

    @staticmethod
    def _request_id(handler_input: HandlerInput) -> str:
        try:
            request = handler_input.request_envelope.request
            return str(request.requestId or "")
        except Exception:
            try:
                return str(handler_input.request_envelope["request"].get("requestId") or "")
            except Exception:
                return ""

    @staticmethod
    def handle_permission_no(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        *,
        deps: object | None = None,
    ):
        d = Onboarding._dependencies(deps)
        d.onboarding.decline_permission(handler_input)
        DialogStateManager.activate(
            handler_input,
            "onboarding",
            context={"stage": OnboardingConstants.ONBOARDING_ASK_TOWN},
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.ONBOARDING_LOCATION_DENIED))
            .reprompt(Ssml.ssml(Speech.REPROMPT_ASK_TOWN))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def handle_returning_user(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        resolved_user_name: Optional[str],
        resolved_locality: Optional[str],
    ):
        source = store.get("lastCompletedSource")
        if isinstance(source, dict):
            content_id = source.get("contentId")
            selected_source = ContentUtils.pick_content_source(source)
            source_name = source.get("sourceName") or (selected_source or {}).get("name")
            source_id = source.get("sourceId") or (selected_source or {}).get("id")
            if (
                source_name
                and source_id
                and (content_id != store.get("lastLatestSourceOfferContentId"))
            ):
                User.update(
                    handler_input,
                    {
                        "pendingLatestSource": source,
                        "lastLatestSourceOfferContentId": content_id,
                    },
                )
                DialogStateManager.activate(handler_input, "latest_source", context=source)
                return (
                    handler_input.response_builder.speak(
                        Ssml.ssml(Speech.LATEST_SOURCE_OFFER(source_name))
                    )
                    .reprompt(Ssml.ssml(Speech.LATEST_SOURCE_REPROMPT(source_name)))
                    .set_should_end_session(False)
                    .response
                )
        city = store.get("userCity") or resolved_locality
        if resolved_user_name and city:
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(Speech.WELCOME_RETURN_NAMED(resolved_user_name, city))
                )
                .set_should_end_session(False)
                .response
            )
        if city:
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.WELCOME_RETURN_CITY(city)))
                .set_should_end_session(False)
                .response
            )
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.WELCOME_RETURN_GENERIC))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def start_town_capture(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        name: Optional[str],
        *,
        deps: object | None = None,
    ):
        """Begin the town-capture flow asking where the user is based."""
        d = Onboarding._dependencies(deps)
        d.onboarding.start_town_capture(handler_input)
        DialogStateManager.activate(
            handler_input,
            "onboarding",
            context={"stage": OnboardingConstants.ONBOARDING_ASK_TOWN},
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.WELCOME_FIRST_ASK_TOWN(name)))
            .reprompt(Ssml.ssml(Speech.REPROMPT_ASK_TOWN))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def resume_town_capture(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        attempted_city: str | None = None,
        *,
        deps: object | None = None,
    ):
        """Retry city capture, then give actionable setup guidance without auto-skipping."""
        d = Onboarding._dependencies(deps)
        attempts = d.onboarding.record_town_attempt(handler_input, store)
        if attempts >= OnboardingConstants.MAX_TOWN_ATTEMPTS:
            speech = Speech.CITY_SETUP_GUIDANCE
        elif attempted_city:
            speech = Speech.CITY_NOT_FOUND(attempted_city)
        else:
            speech = Speech.TOWN_NOT_UNDERSTOOD
        return Onboarding._town_retry_response(handler_input, speech, Speech.REPROMPT_ASK_TOWN)

    @staticmethod
    def handle_town_resolver_unavailable(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        *,
        deps: object | None = None,
    ):
        """Keep one retry in-session, then finish onboarding without location."""
        failures = int(store.get("onboardingTownResolverFailures") or 0) + 1
        d = Onboarding._dependencies(deps)
        if failures < OnboardingConstants.MAX_TOWN_RESOLVER_FAILURES:
            d.onboarding.record_resolver_failure(handler_input, store)
            DialogStateManager.activate(
                handler_input,
                "onboarding",
                context={"stage": OnboardingConstants.ONBOARDING_ASK_TOWN},
            )
            return Onboarding._town_retry_response(
                handler_input,
                Speech.TOWN_LOOKUP_UNAVAILABLE_RETRY,
                Speech.REPROMPT_ASK_TOWN,
            )
        d.onboarding.complete_without_location(handler_input, reliable=False)
        DialogStateManager.clear(handler_input, "onboarding")
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.TOWN_LOOKUP_UNAVAILABLE_CONTINUE))
            .reprompt(Ssml.ssml(Speech.REPROMPT_NO_CITY))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    async def stage_town_confirmation(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        phrase: str,
        *,
        deps: object | None = None,
    ):
        d = Onboarding._dependencies(deps)
        Onboarding.logger.info(
            "Hear: resolving town intent=%s phrase=%r",
            AlexaRequest.get_intent_name(handler_input),
            phrase,
        )
        try:
            await d.progressive.send(handler_input, Speech.LOCATION_PROGRESSIVE)
            options = {
                "alexa_user_id": AlexaRequest.get_user_id(handler_input),
                "prefer_location": True,
                "timeout_ms": DeadlineBudget.resolver_timeout_ms(handler_input),
            }
            if store.get("listenerId"):
                options["listener_id"] = store["listenerId"]
            response = await d.resolver.resolve_utterance(phrase, **options)
            resolution = response.get("resolution") or {}
        except ResolverUnavailable as exc:
            Onboarding.logger.warning("Hear: town resolver unavailable reason=%s", exc)
            return Onboarding.handle_town_resolver_unavailable(handler_input, store, deps=d)
        d.onboarding.reset_resolver_failures(handler_input)
        match = resolution.get("match")
        candidates = resolution.get("candidates") or []
        Onboarding.logger.info(
            "Hear: onboarding town resolution matched=%s city=%s candidates=%s",
            bool(match),
            (match or {}).get("city"),
            len(candidates),
        )
        if not match:
            if candidates:
                names = [candidate["city"] for candidate in candidates[:2]]
                spoken = " or ".join(names)
                d.onboarding.record_town_attempt(handler_input, store)
                return Onboarding._town_retry_response(
                    handler_input,
                    f"Did you mean {spoken}? Please say the full city name.",
                    Speech.REPROMPT_ASK_TOWN,
                )
            normalized_phrase = SearchFilterUtils.normalize_discovery_phrase(phrase)
            if normalized_phrase in OnboardingConstants.TOWN_SKIP_PHRASES:
                return Onboarding.finalize_town_skipped(handler_input, store, deps=d)
            if normalized_phrase in OnboardingConstants.CONTENT_REQUEST_PHRASES:
                d.onboarding.record_town_attempt(handler_input, store)
                return (
                    handler_input.response_builder.speak(Ssml.ssml(Speech.ONBOARDING_DEFER_CONTENT))
                    .reprompt(Ssml.ssml(Speech.REPROMPT_ASK_TOWN))
                    .set_should_end_session(False)
                    .response
                )
            return Onboarding.resume_town_capture(handler_input, store, phrase, deps=d)
        d.onboarding.stage_confirmation(handler_input, match)
        DialogStateManager.activate(
            handler_input,
            "onboarding",
            context={"stage": OnboardingConstants.ONBOARDING_AWAIT_CONFIRM},
        )
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(Speech.ONBOARDING_TOWN_CONFIRM(match["city"]))
            )
            .reprompt(Ssml.ssml(OnboardingConstants.TOWN_CONFIRM_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    async def finalize_town_captured(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        phrase: str,
        *,
        deps: object | None = None,
    ):
        d = Onboarding._dependencies(deps)
        try:
            options = {
                "alexa_user_id": AlexaRequest.get_user_id(handler_input),
                "prefer_location": True,
                "timeout_ms": DeadlineBudget.resolver_timeout_ms(handler_input),
            }
            if store.get("listenerId"):
                options["listener_id"] = store["listenerId"]
            response = await d.resolver.resolve_utterance(phrase, **options)
            resolution = response.get("resolution") or {}
        except ResolverUnavailable as exc:
            Onboarding.logger.warning("Hear: town resolver unavailable reason=%s", exc)
            return Onboarding.handle_town_resolver_unavailable(handler_input, store, deps=d)
        d.onboarding.reset_resolver_failures(handler_input)
        match = resolution.get("match")
        if not match:
            return await Onboarding.stage_town_confirmation(handler_input, store, phrase, deps=d)
        d.onboarding.complete_location(handler_input, {**match, "source": "manual"})
        d.user.update(handler_input, {"awaitingProfilePermission": True})
        DialogStateManager.clear(handler_input, "onboarding")
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(f"{Speech.TOWN_GOT_IT(match['city'])} {Speech.PROFILE_PERMISSION_OFFER}")
            )
            .reprompt(Ssml.ssml(Speech.PROFILE_PERMISSION_OFFER))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def finalize_town_skipped(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        *,
        deps: object | None = None,
    ):
        """Skip town capture and proceed without location."""
        d = Onboarding._dependencies(deps)
        local_playback_pending = bool(store.get("awaitingCommunityPlayback"))
        d.onboarding.complete_without_location(handler_input)
        if local_playback_pending:
            d.user.update(
                handler_input,
                {"awaitingCommunityPlayback": False, "awaitingProfilePermission": False},
            )
            DialogStateManager.clear(handler_input, "onboarding")
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(Speech.COMMUNITY_LOCATION_SKIPPED)
                )
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        d.user.update(handler_input, {"awaitingProfilePermission": True})
        DialogStateManager.clear(handler_input, "onboarding")
        Onboarding.logger.info("Hear: onboarding town skipped")
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.PROFILE_PERMISSION_OFFER))
            .reprompt(Ssml.ssml(Speech.PROFILE_PERMISSION_OFFER))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def handle_location_not_found(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        *,
        deps: object | None = None,
    ):
        """Handle device location lookup failure when permissions are granted."""
        d = Onboarding._dependencies(deps)
        d.onboarding.location_not_found(handler_input)
        DialogStateManager.activate(
            handler_input,
            "onboarding",
            context={"stage": OnboardingConstants.ONBOARDING_ASK_TOWN},
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.LOCATION_NOT_FOUND))
            .reprompt(Ssml.ssml(Speech.REPROMPT_ASK_TOWN))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    async def auto_detect_location_or_manual(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        *,
        deps: object | None = None,
        after_consent: bool = False,
    ):
        d = Onboarding._dependencies(deps)
        await d.progressive.send(handler_input, Speech.LOCATION_PROGRESSIVE)
        match = await d.locality.detect_device_location(handler_input)
        if not match or match.get("_status") == "permission_denied":
            if after_consent:
                return d.permission.location_fallback(handler_input, denied=True)
            return Onboarding.ask_for_permission(handler_input, store, deps=d)
        if match.get("_status") != "resolved":
            d.onboarding.location_not_found(handler_input)
            speech = (
                Speech.LOCATION_PERMISSION_EMPTY
                if match.get("_status") in {"empty", "not_found"}
                else Speech.LOCATION_PERMISSION_UNAVAILABLE
            )
            return (
                handler_input.response_builder.speak(Ssml.ssml(speech))
                .reprompt(Ssml.ssml(Speech.REPROMPT_ASK_TOWN))
                .set_should_end_session(False)
                .response
            )
        city = str(match.get("city") or "").strip()
        has_coordinates = match.get("latitude") is not None and match.get("longitude") is not None
        if not city and not has_coordinates:
            d.onboarding.location_not_found(handler_input)
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.LOCATION_PERMISSION_EMPTY))
                .reprompt(Ssml.ssml(Speech.REPROMPT_ASK_TOWN))
                .set_should_end_session(False)
                .response
            )
        if city and not has_coordinates:
            try:
                options = {
                    "alexa_user_id": AlexaRequest.get_user_id(handler_input),
                    "prefer_location": True,
                    "timeout_ms": DeadlineBudget.resolver_timeout_ms(handler_input),
                }
                if store.get("listenerId"):
                    options["listener_id"] = store["listenerId"]
                response = await d.resolver.resolve_utterance(city, **options)
                resolved = (response.get("resolution") or {}).get("match")
            except ResolverUnavailable as exc:
                Onboarding.logger.warning(
                    "Hear: device-address coordinate resolution unavailable reason=%s",
                    exc,
                )
                resolved = None
            if not resolved:
                Onboarding.logger.info(
                    "Hear: device-address city could not be resolved to coordinates city=%s",
                    city,
                )
                return Onboarding.handle_location_not_found(handler_input, store, deps=d)
            match = {
                **match,
                **resolved,
                "postalCode": match.get("postalCode"),
                "source": "device",
                "_status": "resolved",
            }
            Onboarding.logger.info(
                "Hear: device-address city resolved coordinates=true city=%s",
                match.get("city"),
            )
        d.onboarding.stage_confirmation(handler_input, match, reset_attempts=True)
        DialogStateManager.activate(
            handler_input,
            "onboarding",
            context={"stage": OnboardingConstants.ONBOARDING_AWAIT_CONFIRM},
        )
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(
                    Speech.ONBOARDING_DEVICE_TOWN_CONFIRM(city)
                    if city
                    else Speech.ONBOARDING_DEVICE_LOCATION_CONFIRM
                )
            )
            .reprompt(Ssml.ssml(OnboardingConstants.TOWN_CONFIRM_REPROMPT))
            .set_should_end_session(False)
            .response
        )
