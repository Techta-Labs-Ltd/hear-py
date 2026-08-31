from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.alexa.request import AlexaRequest
from src.models.permission import Permission


class PermissionResumeHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None) -> None:
        self._permission = Permission(deps=deps)

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "SessionResumedRequest"

    async def handle(self, handler_input):
        return await self._permission.resume(handler_input)


class SetUpAccountHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None) -> None:
        self._permission = Permission(deps=deps)

    def can_handle(self, handler_input) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "SetUpAccountIntent"
        )

    async def handle(self, handler_input):
        return self._permission.start_profile(handler_input)
