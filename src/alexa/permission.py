"""Alexa adapter for permission requests and consent completion."""

from __future__ import annotations

import config.permission_scopes as permission_scopes
from src.alexa.context import RequestContext
from src.alexa.dialog import DialogStateManager
from src.alexa.onboarding import Onboarding
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.clients.progressive import ProgressiveResponseClient
from src.constants.onboarding import OnboardingConstants
from src.models.permission_policy import (
    PermissionConstants,
    PermissionPolicy,
)
from src.models.resolver import UtteranceResolver
from src.models.user import User
from src.services.alexa_locality import AlexaLocalityService
from src.services.alexa_profile import ListenerProfileService
from src.services.listener_sync import ListenerSyncService
from src.services.logging_control import ApplicationLog
from src.utils.deadline import DeadlineBudget


class Permission:

    def __init__(
        self,
        user: User,
        onboarding: Onboarding,
        listener_profile: ListenerProfileService,
        listener_sync: ListenerSyncService,
        notification_enable_after_permission,
        progressive: ProgressiveResponseClient,
        locality: AlexaLocalityService,
        resolver: UtteranceResolver,
        resume_local=None,
    ) -> None:
        self._user = user
        self._onboarding = onboarding
        self._listener_profile = listener_profile
        self._listener_sync = listener_sync
        self._notification_enable_after_permission = notification_enable_after_permission
        self._progressive = progressive
        self._locality = locality
        self._resolver = resolver
        self._resume_local = resume_local

    def ask_profile_setup(self, handler_input):
        self._user.update(handler_input, {"awaitingProfileSetupConsent": True})
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.PROFILE_PERMISSION_OFFER))
            .reprompt(Ssml.ssml("Please say yes or no."))
            .set_should_end_session(False)
            .response
        )

    async def start_profile(self, handler_input):
        self._user.update(handler_input, {"awaitingProfileSetupConsent": False})
        if all(
            RequestContext.has_permission(handler_input, scope)
            for scope in PermissionConstants.PROFILE_SCOPES
        ):
            return await self._complete_profile(handler_input)
        return self._begin_manual_profile_town_capture(
            handler_input,
            with_permission_guidance=True,
        )

    def start_notifications(self, handler_input):
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(Speech.NOTIFICATION_PERMISSION_REASON)
            )
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    async def complete_first_run(self, handler_input):
        match = await self._resolved_location(handler_input)
        if match:
            self._onboarding.complete_location(
                handler_input,
                match,
                offer_community_playback=False,
                preserve_postal_code=True,
            )
            DialogStateManager.clear(handler_input, "onboarding")
            await self._sync(handler_input)
            city = match.get("city")
            speech = (
                f"Thanks. I found your location as {city}. You're ready to go. What would you like to listen to?"
                if city
                else "Thanks. I found your location. You're ready to go. What would you like to listen to?"
            )
            return AlexaResponse.present_idle_next(handler_input, speech, Speech.WELCOME_REPROMPT)
        status = (await self._locality.detect_device_location(handler_input)).get("_status")
        self._onboarding.complete_without_location(handler_input)
        DialogStateManager.clear(handler_input, "onboarding")
        await self._sync(handler_input)
        speech = (
            Speech.LOCATION_PERMISSION_DENIED
            if status == "permission_denied"
            else Speech.LOCATION_PERMISSION_EMPTY
            if status in {"empty", "not_found"}
            else Speech.LOCATION_PERMISSION_UNAVAILABLE
        )
        return AlexaResponse.present_idle_next(handler_input, speech, Speech.WELCOME_REPROMPT)

    async def _complete_profile(self, handler_input):
        store = await self._listener_profile.apply_listener_profile(handler_input)
        match = await self._resolved_location(handler_input)
        if not match:
            return self._begin_manual_profile_town_capture(
                handler_input,
                with_permission_guidance=not RequestContext.has_permission(
                    handler_input,
                    permission_scopes.DEVICE_ADDRESS,
                ),
            )
        self._onboarding.complete_location(
            handler_input,
            match,
            offer_community_playback=False,
            preserve_postal_code=True,
        )
        store = self._user.snapshot(handler_input)
        registered = bool(store.get("userEmail") and (store.get("fullName") or store.get("userName")))
        self._user.update(
            handler_input,
            {
                "awaitingProfilePermission": False,
                "awaitingProfileTown": False,
                "profileSetupActive": False,
                "listenerType": "registered" if registered else "listener",
            },
        )
        await self._sync(handler_input)
        if self._user.snapshot(handler_input).get("awaitingCommunityPlayback") and self._resume_local:
            return await self._resume_local(handler_input)
        if registered:
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.PROFILE_PERMISSION_COMPLETE,
                Speech.WELCOME_REPROMPT,
            )
        return self._profile_details_missing(handler_input, store)

    async def _resolved_location(self, handler_input) -> dict | None:
        detected = await self._locality.detect_device_location(handler_input) or {}
        if detected.get("_status") != "resolved":
            return None
        city = str(detected.get("city") or "").strip()
        if not city:
            return None
        try:
            response = await self._resolver.resolve_utterance(
                city,
                alexa_user_id=AlexaRequest.get_user_id(handler_input),
                prefer_location=True,
                timeout_ms=DeadlineBudget.resolver_timeout_ms(handler_input),
            )
        except Exception as error:
            ApplicationLog.warning("Hear: Alexa address location resolution failed error=%s", type(error).__name__)
            return {**detected, "city": city, "locality": city, "source": "device"}
        resolved = (response.get("resolution") or {}).get("match")
        if not resolved:
            return {**detected, "city": city, "locality": city, "source": "device"}
        return {**detected, **resolved, "source": "device"}

    async def _sync(self, handler_input) -> None:
        try:
            await self._listener_sync.sync_for_launch(handler_input)
        except Exception as error:
            ApplicationLog.warning("Hear: listener sync failed error=%s", type(error).__name__)

    def _begin_manual_profile_town_capture(self, handler_input, *, with_permission_guidance=False):
        self._onboarding.begin_town_capture(handler_input)
        self._user.update(
            handler_input,
            {
                "awaitingProfilePermission": False,
                "awaitingProfileTown": True,
                "profileSetupActive": True,
            },
        )
        DialogStateManager.activate(
            handler_input,
            "onboarding",
            context={"stage": OnboardingConstants.ONBOARDING_ASK_TOWN},
        )
        guidance = (
            f"I don't currently have permission to use details from your Alexa account. "
            f"{PermissionPolicy.profile_app_guidance()} "
            if with_permission_guidance
            else ""
        )
        prompt = (
            "Which town or city should I use for your listener profile? "
            "You can say, my city is, followed by your town or city."
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(f"{guidance}{prompt}"))
            .reprompt(
                Ssml.ssml(
                    "Please say, my city is, followed by your town or city. "
                    "For example, my city is Manchester."
                )
            )
            .set_should_end_session(False)
            .response
        )

    def _profile_details_missing(self, handler_input, store: dict):
        missing = []
        if not (store.get("fullName") or store.get("userName")):
            missing.append("your name")
        if not store.get("userEmail"):
            missing.append("your email address")
        details = " and ".join(missing) or "the required details"
        reason = Speech.PROFILE_PERMISSION_MISSING_DETAILS.format(details=details)
        speech = (
            f"{reason} Please check your Alexa profile details and permissions. "
            f"{Speech.PROFILE_PERMISSION_GUEST_CONTINUE}"
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )
