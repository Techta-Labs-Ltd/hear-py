from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.constants.listener import ListenerConstants
from src.models.user import User


class PrincipalType(StrEnum):
    LINKED_PERSON = "linked_person"
    LINKED_HOUSEHOLD = "linked_household"
    ANONYMOUS_PERSON = "anonymous_person"
    ANONYMOUS_INSTALLATION = "anonymous_installation"


@dataclass(frozen=True)
class IdentityContext:
    principal_type: PrincipalType
    alexa_user_id: str | None = None
    person_id: str | None = None
    device_id: str | None = None
    access_token: str | None = None
    is_linked: bool = False


class Listener:
    __slots__ = ("_user",)

    def __init__(self, store: User) -> None:
        self._user = store

    def snapshot(self, handler_input) -> dict:
        return self._user.snapshot(handler_input)

    def apply_profile(self, handler_input, changes: dict) -> dict:
        unsupported = set(changes).difference(ListenerConstants.LISTENER_PROFILE_FIELDS)
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise ValueError(f"unsupported listener profile fields: {names}")
        return self._user.update(handler_input, changes)
