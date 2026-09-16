"""Alexa adapter for permission requests and consent completion."""

from __future__ import annotations

import config.permission_scopes as permission_scopes
from src.alexa.context import RequestContext
from src.alexa.onboarding import Onboarding
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.clients.progressive import ProgressiveResponseClient
from src.constants.onboarding import OnboardingConstants
from src.models.permission_policy import (
    PermissionConstants,
    PermissionPolicy,
    PermissionResumeCommand,
)
from src.models.resolver import UtteranceResolver
from src.models.user import User
from src.services.alexa_locality import AlexaLocalityService
from src.services.alexa_profile import ListenerProfileService
from src.services.listener_sync import ListenerSyncService
from src.services.logging_control import ApplicationLog


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
    ) -> None:
        self._user = user
        self._onboarding = onboarding
        self._listener_profile = listener_profile
        self._listener_sync = listener_sync
        self._notification_enable_after_permission = notification_enable_after_permission
        self._progressive = progressive
        self._locality = locality
        self._resolver = resolver

    def start_location(self, handler_input):
        RequestContext.set_value(handler_input, "_permissionPurpose", PermissionConstants.LOCATION_PURPOSE)
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.ONBOARDING_LOCATION_REASON))
            .add_directive(
                PermissionPolicy.connection_directive(
                    PermissionConstants.LOCATION_PURPOSE,
                    OnboardingConstants.LOCATION_VOICE_PERMISSIONS,
                )
            )
            .response
        )

    def start_profile(self, handler_input):
        self._user.update(handler_input, {"awaitingProfilePermission": True})
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.PROFILE_PERMISSION_REASON))
            .add_directive(
                PermissionPolicy.connection_directive(
                    PermissionConstants.PROFILE_PURPOSE,
                    PermissionConstants.PROFILE_SCOPES,
                )
            )
            .response
        )

    def start_notifications(self, handler_input):
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(Speech.NOTIFICATION_PERMISSION_REASON)
            )
            .add_directive(
                PermissionPolicy.connection_directive(
                    PermissionConstants.NOTIFICATION_PURPOSE,
                    (permission_scopes.NOTIFICATIONS_WRITE,),
                )
            )
            .response
        )

    async def resume(self, handler_input, command: PermissionResumeCommand):
        store = self._user.snapshot(handler_input)
        decision = PermissionPolicy.resume_decision(
            command,
            awaiting_profile_permission=bool(store.get("awaitingProfilePermission")),
        )
        ApplicationLog.info(
            "Hear: permission consent resumed purpose=%s status=%s connectionCode=%s decision=%s",
            decision.command.purpose or "unknown",
            decision.command.status or "missing",
            decision.command.connection_code or "missing",
            decision.kind,
        )
        if decision.kind == "location_granted":
            return await Onboarding.auto_detect_location_or_manual(
                handler_input,
                self._user.snapshot(handler_input),
                self._onboarding,
                self._progressive,
                self._locality,
                self._resolver,
                lambda current_input, current_store: Onboarding.ask_for_permission(
                    current_input, current_store, self._onboarding
                ),
                self.location_fallback,
                lambda current_input, current_store: Onboarding.handle_location_not_found(
                    current_input, current_store, self._onboarding
                ),
                after_consent=True,
            )
        if decision.kind == "profile_granted":
            return await self._complete_profile(handler_input)
        if decision.kind == "notifications_granted":
            return self._notification_enable_after_permission(handler_input)
        if decision.kind == "notifications_denied":
            return AlexaResponse.present_idle_next(
                handler_input,
                "Ok. Notifications will stay off.",
                Speech.WELCOME_REPROMPT,
            )
        if decision.kind == "profile_denied":
            self._user.update(handler_input, {"awaitingProfilePermission": False})
            return self._profile_permission_failure(
                handler_input,
                status=decision.command.status,
                connection_code=decision.command.connection_code,
            )
        return self.location_fallback(handler_input, denied=True)

    async def _complete_profile(self, handler_input):
        store = await self._listener_profile.apply_listener_profile(handler_input)
        registered = bool(store.get("userEmail") and (store.get("fullName") or store.get("userName")))
        self._user.update(
            handler_input,
            {
                "awaitingProfilePermission": False,
                "listenerType": "registered" if registered else "guest",
            },
        )
        try:
            await self._listener_sync.sync_for_launch(handler_input)
        except Exception as error:
            ApplicationLog.warning("Hear: post-consent listener sync failed error=%s", type(error).__name__)
        if registered:
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.PROFILE_PERMISSION_COMPLETE,
                Speech.WELCOME_REPROMPT,
            )
        return self._profile_details_missing(handler_input, store)

    @staticmethod
    def _profile_failure_reason(*, status: str, connection_code: str) -> str:
        if status == "DENIED":
            return Speech.PROFILE_PERMISSION_DENIED
        if status == "NOT_ANSWERED" or connection_code == "204":
            return Speech.PROFILE_PERMISSION_NOT_ANSWERED
        if status == "REDIRECT_TO_APP":
            return Speech.PROFILE_PERMISSION_APP_REQUIRED
        return Speech.PROFILE_PERMISSION_FAILED

    def _profile_permission_failure(
        self,
        handler_input,
        *,
        status: str,
        connection_code: str,
    ):
        speech = (
            f"{self._profile_failure_reason(status=status, connection_code=connection_code)} "
            f"{PermissionPolicy.profile_app_guidance()} "
            f"{Speech.PROFILE_PERMISSION_GUEST_CONTINUE}"
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .with_ask_for_permissions_consent_card(PermissionConstants.PROFILE_SCOPES)
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
            .with_ask_for_permissions_consent_card(PermissionConstants.PROFILE_SCOPES)
            .set_should_end_session(False)
            .response
        )

    def location_fallback(self, handler_input, *, denied: bool):
        self._onboarding.decline_permission(handler_input)
        speech = Speech.LOCATION_PERMISSION_DENIED if denied else Speech.LOCATION_PERMISSION_UNAVAILABLE
        speech = f"{speech} {PermissionPolicy.app_guidance()}"
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Ssml.ssml(Speech.REPROMPT_ASK_TOWN))
            .set_should_end_session(False)
            .response
        )
