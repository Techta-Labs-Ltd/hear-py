from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ask_sdk_core.handler_input import HandlerInput

from src.alexa.context import RequestContext
from src.alexa.dialog import DialogSelection, DialogStateManager
from src.alexa.onboarding_state import OnboardingService, OnboardingState
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.constants.discovery import DiscoveryConstants
from src.constants.onboarding import OnboardingConstants
from src.models.resolver import ResolverUnavailable
from src.models.user import User
from src.services.logging_control import ApplicationLog
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
    __slots__ = (
        "_user",
        "_onboarding",
        "_finalize_town_skipped",
        "_stage_town_confirmation",
    )

    def __init__(
        self,
        user: User,
        onboarding: OnboardingService,
        finalize_town_skipped,
        stage_town_confirmation,
    ) -> None:
        self._user = user
        self._onboarding = onboarding
        self._finalize_town_skipped = finalize_town_skipped
        self._stage_town_confirmation = stage_town_confirmation

    async def execute(self, handler_input: HandlerInput):
        store = self._user.snapshot(handler_input)
        intent_name = AlexaRequest.get_intent_name(handler_input)
        if intent_name in (
            "AMAZON.NoIntent",
            "SkipFeedbackIntent",
            "AMAZON.NextIntent",
            "AMAZON.SkipIntent",
            "AMAZON.CancelIntent",
        ):
            return self._finalize_town_skipped(handler_input, store)
        attrs = RequestContext.request(handler_input)
        nlp = attrs.get("_nlp", {}) if attrs else {}
        nlp_slots = nlp.get("slots", {}) if nlp else {}
        town = (
            nlp_slots.get("location")
            or nlp_slots.get("townName")
            or nlp_slots.get("placeName")
        )
        if not town:
            town = (
                AlexaRequest.get_slot_value(handler_input, "location")
                or AlexaRequest.get_slot_value(handler_input, "townName")
                or AlexaRequest.get_slot_value(handler_input, "city")
            )
        if town:
            return await self._stage_town_confirmation(handler_input, store, town)
        return Onboarding.resume_town_capture(
            handler_input, store, self._onboarding
        )

class SetLocation:
    __slots__ = ("_user", "_onboarding", "_stage_town_confirmation")

    def __init__(self, user: User, onboarding: OnboardingService, stage_town_confirmation) -> None:
        self._user = user
        self._onboarding = onboarding
        self._stage_town_confirmation = stage_town_confirmation

    async def execute(self, handler_input: HandlerInput):
        attrs = RequestContext.request(handler_input)
        nlp = attrs.get("_nlp", {}) if attrs else {}
        nlp_slots = nlp.get("slots", {}) or {}
        town = nlp_slots.get("location") or nlp_slots.get("townName")
        if town:
            return await self._stage_town_confirmation(
                handler_input,
                self._user.snapshot(handler_input),
                town,
            )
        self._onboarding.request_location_change(handler_input)
        DialogStateManager.activate(
            handler_input,
            "onboarding",
            context={"stage": OnboardingConstants.ONBOARDING_ASK_TOWN},
        )
        return Onboarding._town_retry_response(
            handler_input,
            "Sure. Which town or city are you in now?",
            "Which town or city should I set as your location?",
            capture_profile_town=True,
        )


class Onboarding(OnboardingService):

    def __init__(self, store: User | None = None) -> None:
        super().__init__(OnboardingState(store or User()))

    @staticmethod
    def _town_resolver_utterance(phrase: str) -> str:
        value = " ".join(str(phrase or "").strip().split())
        if not value:
            return value
        lowered = value.casefold()
        location_carriers = (
            "my city is ",
            "my town is ",
            "my area is ",
            "i am in ",
            "i'm in ",
            "i live in ",
            "set my location to ",
            "set my city to ",
            "change my location to ",
            "change my city to ",
        )
        return value if lowered.startswith(location_carriers) else f"my city is {value}"

    @staticmethod
    def _town_ambiguity_candidates(response: dict) -> list[dict]:
        references = (
            response.get("ambiguities")
            or (response.get("slots") or {}).get("ambiguousReferences")
            or []
        )
        candidates: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for reference in references:
            nested = reference.get("candidates") if isinstance(reference, dict) else None
            values = nested if isinstance(nested, list) and nested else [reference]
            for candidate in values:
                if not isinstance(candidate, dict):
                    continue
                entity_type = str(
                    candidate.get("type") or candidate.get("entityType") or ""
                ).casefold()
                name = str(
                    candidate.get("name")
                    or candidate.get("canonicalValue")
                    or candidate.get("city")
                    or ""
                ).strip()
                if entity_type != "location" or not name:
                    continue
                entity_id = str(candidate.get("id") or candidate.get("entityId") or "")
                key = (entity_id, name.casefold())
                if key in seen:
                    continue
                seen.add(key)
                normalized = {
                    "type": "location",
                    "id": entity_id,
                    "name": name,
                }
                for source_key, target_key in (
                    ("countryCode", "countryCode"),
                    ("latitude", "latitude"),
                    ("longitude", "longitude"),
                    ("county", "county"),
                    ("locationType", "locationType"),
                    ("label", "label"),
                ):
                    if candidate.get(source_key) is not None:
                        normalized[target_key] = candidate[source_key]
                candidates.append(normalized)
        return candidates[: DiscoveryConstants.CHOICE_PAGE_SIZE]

    @staticmethod
    def _town_ambiguity_choice(phrase: str, candidates: list[dict]) -> dict | None:
        if not candidates:
            return None
        normalized = DialogSelection.normalize_ordinal(phrase)
        ordinal = DiscoveryConstants.ORDINAL_INDEX.get(normalized)
        if ordinal is not None and ordinal < len(candidates):
            return candidates[ordinal]
        return DialogSelection.closest_candidate(phrase, candidates)

    @staticmethod
    def _town_candidate_match(candidate: dict) -> dict:
        name = str(candidate.get("name") or "").strip()
        match = {
            "city": name,
            "locality": name,
            "source": "manual",
        }
        for key in ("countryCode", "latitude", "longitude", "county", "locationType"):
            if candidate.get(key) is not None:
                match[key] = candidate[key]
        return match

    @staticmethod
    def _town_ambiguity_speech(candidates: list[dict]) -> tuple[str, str]:
        names = [
            Speech.escape_ssml_lite(
                str(candidate.get("label") or candidate.get("name") or "").strip()
            )
            for candidate in candidates
            if str(candidate.get("name") or "").strip()
        ]
        labels = ("First", "Second", "Third")
        choices = " ".join(
            f"{labels[index]}, {name}." for index, name in enumerate(names[:3])
        )
        if len(names) <= 1:
            ordinals = "first"
        elif len(names) == 2:
            ordinals = "first or second"
        else:
            ordinals = "first, second, or third"
        speech = (
            f"I found a few places that sound similar. {choices} "
            f"Which one did you mean? You can say the name, or {ordinals}."
        )
        reprompt = f"Please say the place name, or {ordinals}. You can also say skip."
        return speech, reprompt

    @staticmethod
    def _town_retry_response(
        handler_input: HandlerInput,
        speech: str,
        reprompt: str,
        capture_profile_town: bool = False,
        consent_permissions: list[str] | None = None,
    ):
        """Keep Alexa's active location intent open so a bare town fills its slot."""
        builder = handler_input.response_builder.speak(Ssml.ssml(speech)).reprompt(
            Ssml.ssml(reprompt)
        )
        if consent_permissions:
            builder = builder.with_ask_for_permissions_consent_card(consent_permissions)
        intent_name = AlexaRequest.get_intent_name(handler_input)
        slot_name = {
            "TownCaptureIntent": "location",
            "SetLocationIntent": "location",
            "SearchLocationIntent": "location",
        }.get(intent_name) if intent_name else None
        if capture_profile_town and intent_name != "TownCaptureIntent":
            builder = builder.add_directive(
                {
                    "type": "Dialog.ElicitSlot",
                    "slotToElicit": "location",
                    "updatedIntent": {
                        "name": "TownCaptureIntent",
                        "confirmationStatus": "NONE",
                        "slots": {
                            "location": {
                                "name": "location",
                                "confirmationStatus": "NONE",
                            }
                        },
                    },
                }
            )
        elif slot_name:
            builder = builder.add_directive(
                {"type": "Dialog.ElicitSlot", "slotToElicit": slot_name}
            )
        return builder.set_should_end_session(False).response

    @staticmethod
    def onboarding_pending_redirect(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        onboarding: OnboardingService,
    ):
        stage = store.get("onboardingStage")
        if stage == OnboardingConstants.ONBOARDING_ASK_TOWN:
            return Onboarding.resume_town_capture(handler_input, store, onboarding)
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
        onboarding: OnboardingService,
    ):
        """Prompt the user to grant location permission."""
        onboarding.ask_permission(handler_input)
        DialogStateManager.activate(
            handler_input, "onboarding", context={"stage": "ask_permission"}
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.ONBOARDING_ASK_PERMISSION))
            .with_simple_card("Learn more about Hear", "https://hear.media/alexa")
            .reprompt(
                Ssml.ssml("May I check the address saved in your Alexa account? Please say yes or no.")
            )
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def handle_permission_no(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        onboarding: OnboardingService,
    ):
        onboarding.complete_without_location(handler_input)
        DialogStateManager.clear(handler_input, "onboarding")
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.PROFILE_PERMISSION_SKIPPED))
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
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
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.WELCOME_RETURN_NAMED(resolved_user_name, city),
            )
        if city:
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.WELCOME_RETURN_CITY(city),
            )
        return AlexaResponse.present_idle_next(
            handler_input,
            Speech.WELCOME_RETURN_GENERIC,
        )

    @staticmethod
    def resume_town_capture(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        onboarding: OnboardingService,
        attempted_city: str | None = None,
        speech_override: str | None = None,
    ):
        """Retry city capture, then give actionable setup guidance without auto-skipping."""
        attempts = onboarding.record_town_attempt(handler_input, store)
        if attempts >= OnboardingConstants.MAX_TOWN_ATTEMPTS:
            onboarding.complete_without_location(handler_input, reliable=False)
            DialogStateManager.clear(handler_input, "onboarding")
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.CITY_SETUP_GUIDANCE))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        if speech_override:
            speech = speech_override
        elif attempted_city:
            speech = Speech.CITY_NOT_FOUND(attempted_city)
        else:
            speech = Speech.TOWN_NOT_UNDERSTOOD
        return Onboarding._town_retry_response(
            handler_input,
            speech,
            Speech.REPROMPT_ASK_TOWN,
            capture_profile_town=bool(
                store.get("profileSetupActive") or store.get("awaitingProfileTown")
            ),
        )

    @staticmethod
    def handle_town_resolver_unavailable(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        onboarding: OnboardingService,
    ):
        """Keep one retry in-session, then finish onboarding without location."""
        failures = int(store.get("onboardingTownResolverFailures") or 0) + 1
        if failures < OnboardingConstants.MAX_TOWN_RESOLVER_FAILURES:
            onboarding.record_resolver_failure(handler_input, store)
            DialogStateManager.activate(
                handler_input,
                "onboarding",
                context={"stage": OnboardingConstants.ONBOARDING_ASK_TOWN},
            )
            return Onboarding._town_retry_response(
                handler_input,
                Speech.TOWN_LOOKUP_UNAVAILABLE_RETRY,
                Speech.REPROMPT_ASK_TOWN,
                capture_profile_town=bool(
                    store.get("profileSetupActive") or store.get("awaitingProfileTown")
                ),
            )
        onboarding.complete_without_location(handler_input, reliable=False)
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
        onboarding: OnboardingService,
        progressive,
        resolver,
        finalize_town_skipped,
    ):
        ApplicationLog.info(
            "Hear: resolving town intent=%s phrasePresent=%s profileTown=%s",
            AlexaRequest.get_intent_name(handler_input),
            bool(phrase),
            bool(store.get("profileSetupActive") and store.get("awaitingProfileTown")),
        )
        normalized_phrase = SearchFilterUtils.normalize_discovery_phrase(phrase)
        if normalized_phrase in OnboardingConstants.TOWN_SKIP_PHRASES:
            return finalize_town_skipped(handler_input, store)
        if normalized_phrase in OnboardingConstants.CONTENT_REQUEST_PHRASES:
            return Onboarding.resume_town_capture(
                handler_input, store, onboarding, speech_override=Speech.ONBOARDING_DEFER_CONTENT
            )

        pending = store.get("pendingTownAmbiguity")
        selected_candidate = None
        if isinstance(pending, dict):
            pending_candidates = list(pending.get("candidates") or [])
            selected_candidate = Onboarding._town_ambiguity_choice(
                phrase, pending_candidates
            )
            if selected_candidate:
                phrase = str(selected_candidate.get("name") or phrase).strip()
                onboarding.clear_town_ambiguity(handler_input)
            elif DialogSelection.normalize_ordinal(phrase) in DiscoveryConstants.ORDINAL_INDEX:
                speech, _ = Onboarding._town_ambiguity_speech(pending_candidates)
                return Onboarding.resume_town_capture(
                    handler_input, store, onboarding, speech_override=speech
                )
            else:
                onboarding.clear_town_ambiguity(handler_input)

        try:
            await progressive.send(handler_input, Speech.LOCATION_PROGRESSIVE)
            options = {
                "alexa_user_id": AlexaRequest.get_user_id(handler_input),
                "prefer_location": True,
                "timeout_ms": DeadlineBudget.resolver_timeout_ms(handler_input),
            }
            if store.get("listenerId"):
                options["listener_id"] = store["listenerId"]
            resolver_utterance = Onboarding._town_resolver_utterance(phrase)
            response = await resolver.resolve_utterance(resolver_utterance, **options)
            resolution = response.get("resolution") or {}
        except ResolverUnavailable as exc:
            ApplicationLog.warning("Hear: town resolver unavailable error=%s", type(exc).__name__)
            return Onboarding.handle_town_resolver_unavailable(handler_input, store, onboarding)
        onboarding.reset_resolver_failures(handler_input)
        match = resolution.get("match")
        resolver_candidates = resolution.get("candidates") or []
        ambiguity_candidates = Onboarding._town_ambiguity_candidates(response)
        ApplicationLog.info(
            "Hear: onboarding town resolution matched=%s candidates=%s ambiguities=%s",
            bool(match),
            len(resolver_candidates),
            len(ambiguity_candidates),
        )
        if not match and selected_candidate:
            match = Onboarding._town_candidate_match(selected_candidate)
        if not match and ambiguity_candidates:
            onboarding.stage_town_ambiguity(
                handler_input, phrase, ambiguity_candidates
            )
            speech, reprompt = Onboarding._town_ambiguity_speech(
                ambiguity_candidates
            )
            return Onboarding._town_retry_response(
                handler_input,
                speech,
                reprompt,
                capture_profile_town=True,
            )
        if not match and resolver_candidates:
            candidates = [
                {
                    "type": "location",
                    "id": str(candidate.get("id") or candidate.get("entityId") or ""),
                    "name": str(candidate.get("city") or candidate.get("name") or "").strip(),
                    **{
                        key: candidate[key]
                        for key in ("countryCode", "latitude", "longitude", "county", "locationType")
                        if candidate.get(key) is not None
                    },
                }
                for candidate in resolver_candidates[: DiscoveryConstants.CHOICE_PAGE_SIZE]
                if str(candidate.get("city") or candidate.get("name") or "").strip()
            ]
            if candidates:
                onboarding.stage_town_ambiguity(handler_input, phrase, candidates)
                speech, reprompt = Onboarding._town_ambiguity_speech(candidates)
                return Onboarding._town_retry_response(
                    handler_input, speech, reprompt, capture_profile_town=True
                )
        if not match:
            return Onboarding.resume_town_capture(
                handler_input, store, onboarding, phrase
            )
        onboarding.clear_town_ambiguity(handler_input)
        onboarding.stage_confirmation(handler_input, match)
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
        onboarding: OnboardingService,
        user: User,
        resolver,
        stage_town_confirmation,
    ):
        try:
            options = {
                "alexa_user_id": AlexaRequest.get_user_id(handler_input),
                "prefer_location": True,
                "timeout_ms": DeadlineBudget.resolver_timeout_ms(handler_input),
            }
            if store.get("listenerId"):
                options["listener_id"] = store["listenerId"]
            response = await resolver.resolve_utterance(
                Onboarding._town_resolver_utterance(phrase), **options
            )
            resolution = response.get("resolution") or {}
        except ResolverUnavailable as exc:
            ApplicationLog.warning("Hear: town resolver unavailable error=%s", type(exc).__name__)
            return Onboarding.handle_town_resolver_unavailable(handler_input, store, onboarding)
        onboarding.reset_resolver_failures(handler_input)
        match = resolution.get("match")
        if not match:
            return await stage_town_confirmation(handler_input, store, phrase)
        onboarding.complete_location(handler_input, {**match, "source": "manual"})
        user.update(handler_input, {"awaitingProfilePermission": True})
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
        onboarding: OnboardingService,
        user: User,
    ):
        """Skip town capture and proceed without location."""
        local_playback_pending = bool(store.get("awaitingCommunityPlayback"))
        onboarding.complete_without_location(handler_input)
        if store.get("profileSetupActive"):
            user.update(
                handler_input,
                {
                    "awaitingProfilePermission": False,
                    "awaitingProfileTown": False,
                    "profileSetupActive": False,
                },
            )
            DialogStateManager.clear(handler_input, "onboarding")
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.CITY_SETUP_GUIDANCE))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        if local_playback_pending:
            user.update(
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
        user.update(handler_input, {"awaitingProfilePermission": True})
        DialogStateManager.clear(handler_input, "onboarding")
        ApplicationLog.info("Hear: onboarding town skipped")
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.PROFILE_PERMISSION_OFFER))
            .reprompt(Ssml.ssml(Speech.PROFILE_PERMISSION_OFFER))
            .set_should_end_session(False)
            .response
        )
