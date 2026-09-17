from __future__ import annotations

from src.alexa.context import RequestContext
from src.constants.listener import ListenerConstants
from src.models.listener import IdentityContext


class Listener:
    __slots__ = ("_user",)

    def __init__(self, user) -> None:
        self._user = user

    def snapshot(self, handler_input) -> dict:
        return self._user.snapshot(handler_input)

    @staticmethod
    def identity(handler_input) -> IdentityContext | None:
        identity = RequestContext.value(handler_input, "_identity")
        return identity if isinstance(identity, IdentityContext) else None

    @staticmethod
    def set_identity(handler_input, identity: IdentityContext) -> IdentityContext:
        return RequestContext.set_value(handler_input, "_identity", identity)

    def apply_profile(self, handler_input, changes: dict) -> dict:
        unsupported = set(changes).difference(ListenerConstants.LISTENER_PROFILE_FIELDS)
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise ValueError(f"unsupported listener profile fields: {names}")
        return self._user.update(handler_input, changes)
