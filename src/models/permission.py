from __future__ import annotations

import logging

import config.permission_scopes as permission_scopes
from config import settings
from src.alexa.context import RequestContext
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.constants.onboarding import OnboardingConstants
from src.models.onboarding import Onboarding


class PermissionConstants:
    CONNECTION_URI = "connection://AMAZON.AskForPermissionsConsent/2"
    LOCATION_PURPOSE = "onboarding_location"
    PROFILE_PURPOSE = "listener_profile"
    NOTIFICATION_PURPOSE = "notifications"
    PROFILE_SCOPES = (
        permission_scopes.PROFILE_NAME_READ,
        permission_scopes.PROFILE_EMAIL_READ,
    )


class PermissionPolicy:
    @staticmethod
    def skill_name() -> str:
        return "Hear service" if settings.STAGE == "production" else "test development"

    @staticmethod
    def connection_directive(purpose: str, scopes: tuple[str, ...]) -> dict:
        return {
            "type": "Connections.StartConnection",
            "uri": PermissionConstants.CONNECTION_URI,
            "input": {
                "@type": "AskForPermissionsConsentRequest",
                "@version": "2",
                "permissionScopes": [
                    {"permissionScope": scope, "consentLevel": "ACCOUNT"}
                    for scope in scopes
                ],
            },
            "token": purpose,
        }

    @staticmethod
    def resume_result(handler_input) -> tuple[str, str]:
        request = getattr(handler_input.request_envelope, "request", {}) or {}
        cause = request.get("cause", {}) if isinstance(request, dict) else getattr(request, "cause", {})
        token = cause.get("token", "") if isinstance(cause, dict) else getattr(cause, "token", "")
        result = cause.get("result", {}) if isinstance(cause, dict) else getattr(cause, "result", {})
        status = result.get("status", "") if isinstance(result, dict) else getattr(result, "status", "")
        return str(token or ""), str(status or "")

    @staticmethod
    def app_guidance() -> str:
        return f"You can also enable permissions in the Alexa app under {PermissionPolicy.skill_name()}, Settings, Manage Permissions."


class Permission:
    logger = logging.getLogger(__name__)

    def __init__(self, *, deps: object | None = None) -> None:
        if deps is None:
            raise RuntimeError("Permission requires injected dependencies")
        self._deps = deps

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
        self._deps.user.update(handler_input, {"awaitingProfilePermission": True})
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

    async def resume(self, handler_input):
        purpose, status = PermissionPolicy.resume_result(handler_input)
        accepted = status.upper() == "ACCEPTED"
        if purpose == PermissionConstants.LOCATION_PURPOSE and accepted:
            return await Onboarding.auto_detect_location_or_manual(
                handler_input,
                self._deps.user.snapshot(handler_input),
                deps=self._deps,
                after_consent=True,
            )
        if purpose == PermissionConstants.PROFILE_PURPOSE and accepted:
            return await self._complete_profile(handler_input)
        if purpose == PermissionConstants.NOTIFICATION_PURPOSE and accepted:
            return self._deps.notifications.enable_after_permission(handler_input)
        if purpose == PermissionConstants.NOTIFICATION_PURPOSE:
            return AlexaResponse.present_idle_next(
                handler_input,
                "No problem. Notifications will stay off.",
                Speech.WELCOME_REPROMPT,
            )
        if purpose == PermissionConstants.PROFILE_PURPOSE:
            self._deps.user.update(handler_input, {"awaitingProfilePermission": False})
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.PROFILE_PERMISSION_FAILED,
                Speech.WELCOME_REPROMPT,
            )
        return self.location_fallback(handler_input, denied=True)

    async def _complete_profile(self, handler_input):
        store = await self._deps.listener_profile.apply_listener_profile(handler_input)
        registered = bool(store.get("userEmail") and (store.get("fullName") or store.get("userName")))
        self._deps.user.update(
            handler_input,
            {
                "awaitingProfilePermission": False,
                "listenerType": "registered" if registered else "guest",
            },
        )
        try:
            await self._deps.listener_sync.sync_for_launch(handler_input)
        except Exception as error:
            self.logger.warning("Hear: post-consent listener sync failed error=%s", type(error).__name__)
        return AlexaResponse.present_idle_next(
            handler_input,
            Speech.PROFILE_PERMISSION_COMPLETE if registered else Speech.PROFILE_PERMISSION_FAILED,
            Speech.WELCOME_REPROMPT,
        )

    def location_fallback(self, handler_input, *, denied: bool):
        self._deps.onboarding.decline_permission(handler_input)
        speech = Speech.LOCATION_PERMISSION_DENIED if denied else Speech.LOCATION_PERMISSION_UNAVAILABLE
        speech = f"{speech} {PermissionPolicy.app_guidance()}"
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Ssml.ssml(Speech.REPROMPT_ASK_TOWN))
            .set_should_end_session(False)
            .response
        )
