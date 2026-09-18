from __future__ import annotations

import config.permission_scopes as permission_scopes
from config import settings


class PermissionConstants:
    PROFILE_SCOPES = (
        permission_scopes.PROFILE_NAME_READ,
        permission_scopes.PROFILE_EMAIL_READ,
    )


class PermissionPolicy:
    @staticmethod
    def skill_name() -> str:
        return "Hear service" if settings.STAGE == "production" else "test development"

    @staticmethod
    def app_guidance() -> str:
        return f"You can also enable permissions in the Alexa app under {PermissionPolicy.skill_name()}, Settings, Manage Permissions."

    @staticmethod
    def profile_app_guidance() -> str:
        return (
            "Open the Alexa app, then go to "
            f"{PermissionPolicy.skill_name()}, Settings, then Manage Permissions."
        )
