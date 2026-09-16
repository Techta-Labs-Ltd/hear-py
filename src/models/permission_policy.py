from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import config.permission_scopes as permission_scopes
from config import settings


class PermissionConstants:
    CONNECTION_URI = "connection://AMAZON.AskForPermissionsConsent/2"
    LOCATION_PURPOSE = "onboarding_location"
    PROFILE_PURPOSE = "listener_profile"
    NOTIFICATION_PURPOSE = "notifications"
    PROFILE_SCOPES = (
        permission_scopes.PROFILE_NAME_READ,
        permission_scopes.PROFILE_EMAIL_READ,
    )


@dataclass(frozen=True, slots=True)
class PermissionResumeCommand:
    purpose: str = ""
    status: str = ""
    connection_code: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "purpose", str(self.purpose or ""))
        object.__setattr__(self, "status", str(self.status or "").upper())
        object.__setattr__(self, "connection_code", str(self.connection_code or ""))


@dataclass(frozen=True, slots=True)
class PermissionResumeDecision:
    kind: Literal[
        "location_granted",
        "location_denied",
        "profile_granted",
        "profile_denied",
        "notifications_granted",
        "notifications_denied",
    ]
    command: PermissionResumeCommand


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
    def resume_decision(
        command: PermissionResumeCommand, *, awaiting_profile_permission: bool
    ) -> PermissionResumeDecision:
        purpose = command.purpose or (
            PermissionConstants.PROFILE_PURPOSE if awaiting_profile_permission else ""
        )
        normalized = PermissionResumeCommand(
            purpose=purpose,
            status=command.status,
            connection_code=command.connection_code,
        )
        accepted = (
            normalized.connection_code in {"", "200"}
            and normalized.status == "ACCEPTED"
        )
        kind: Literal[
            "location_granted",
            "location_denied",
            "profile_granted",
            "profile_denied",
            "notifications_granted",
            "notifications_denied",
        ]
        if normalized.purpose == PermissionConstants.LOCATION_PURPOSE:
            kind = "location_granted" if accepted else "location_denied"
        elif normalized.purpose == PermissionConstants.PROFILE_PURPOSE:
            kind = "profile_granted" if accepted else "profile_denied"
        elif normalized.purpose == PermissionConstants.NOTIFICATION_PURPOSE:
            kind = "notifications_granted" if accepted else "notifications_denied"
        else:
            kind = "location_denied"
        return PermissionResumeDecision(kind, normalized)

    @staticmethod
    def app_guidance() -> str:
        return f"You can also enable permissions in the Alexa app under {PermissionPolicy.skill_name()}, Settings, Manage Permissions."

    @staticmethod
    def profile_app_guidance() -> str:
        return (
            "Open the Alexa app and use the permission card, or go to "
            f"{PermissionPolicy.skill_name()}, Settings, then Manage Permissions."
        )
