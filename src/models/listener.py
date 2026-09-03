from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from config import settings
from src.alexa.context import RequestContext
from src.constants.listener import ListenerConstants
from src.models.user import User


class PrincipalType(StrEnum):
    RECOGNIZED_PERSON = "recognized_person"
    SKILL_USER = "skill_user"


@dataclass(frozen=True)
class IdentityContext:
    principal_type: PrincipalType
    alexa_user_id: str | None = None
    person_id: str | None = None
    device_id: str | None = None
    skill_id: str | None = None
    locale: str | None = None
    user_email: str | None = None
    listener_id: str | None = None

    def resolution_payload(self) -> dict:
        return {
            key: value
            for key, value in {
                "alexaUserId": self.alexa_user_id,
                "personId": self.person_id,
                "deviceId": self.device_id,
                "skillId": self.skill_id,
                "locale": self.locale,
                "userEmail": self.user_email,
                "environment": settings.STAGE,
                "principalType": self.principal_type.value,
                "clientVersion": settings.HEAR_CLIENT_VERSION,
            }.items()
            if value is not None
        }


class Listener:
    __slots__ = ("_user",)

    def __init__(self, store: User) -> None:
        self._user = store

    def snapshot(self, handler_input) -> dict:
        return self._user.snapshot(handler_input)

    @staticmethod
    def identity(handler_input) -> IdentityContext | None:
        identity = RequestContext.value(handler_input, "_identity")
        return identity if isinstance(identity, IdentityContext) else None

    def apply_profile(self, handler_input, changes: dict) -> dict:
        unsupported = set(changes).difference(ListenerConstants.LISTENER_PROFILE_FIELDS)
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise ValueError(f"unsupported listener profile fields: {names}")
        return self._user.update(handler_input, changes)
