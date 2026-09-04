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
    def resume_result(handler_input) -> tuple[str, str, str, str]:
        request = getattr(handler_input.request_envelope, "request", {}) or {}
        cause = request.get("cause", {}) if isinstance(request, dict) else getattr(request, "cause", {})
        token = cause.get("token", "") if isinstance(cause, dict) else getattr(cause, "token", "")
        result = cause.get("result", {}) if isinstance(cause, dict) else getattr(cause, "result", {})
        status = result.get("status", "") if isinstance(result, dict) else getattr(result, "status", "")
        connection = cause.get("status", {}) if isinstance(cause, dict) else getattr(cause, "status", {})
        code = connection.get("code", "") if isinstance(connection, dict) else getattr(connection, "code", "")
        message = connection.get("message", "") if isinstance(connection, dict) else getattr(connection, "message", "")
        return (
            str(token or ""),
            str(status or ""),
            str(code or ""),
            str(message or ""),
        )

    @staticmethod
    def app_guidance() -> str:
        return f"You can also enable permissions in the Alexa app under {PermissionPolicy.skill_name()}, Settings, Manage Permissions."

    @staticmethod
    def profile_app_guidance() -> str:
        return (
            "Open the Alexa app and use the permission card, or go to "
            f"{PermissionPolicy.skill_name()}, Settings, then Manage Permissions."
        )


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
        purpose, status, connection_code, connection_message = PermissionPolicy.resume_result(
            handler_input
        )
        store = self._deps.user.snapshot(handler_input)
        if not purpose and store.get("awaitingProfilePermission"):
            purpose = PermissionConstants.PROFILE_PURPOSE
        normalized_status = status.upper()
        accepted = connection_code in {"", "200"} and normalized_status == "ACCEPTED"
        self.logger.info(
            "Hear: permission consent resumed purpose=%s status=%s connectionCode=%s connectionMessage=%s",
            purpose or "unknown",
            normalized_status or "missing",
            connection_code or "missing",
            connection_message or "missing",
        )
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
            return self._profile_permission_failure(
                handler_input,
                status=normalized_status,
                connection_code=connection_code,
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
        self._deps.onboarding.decline_permission(handler_input)
        speech = Speech.LOCATION_PERMISSION_DENIED if denied else Speech.LOCATION_PERMISSION_UNAVAILABLE
        speech = f"{speech} {PermissionPolicy.app_guidance()}"
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Ssml.ssml(Speech.REPROMPT_ASK_TOWN))
            .set_should_end_session(False)
            .response
        )
