from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.alexa.permission import Permission
from src.alexa.request import AlexaRequest


class SetUpAccountHandler(AbstractRequestHandler):
    def __init__(self, permission: Permission) -> None:
        self._permission = permission

    def can_handle(self, handler_input) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "SetUpAccountIntent"
        )

    async def handle(self, handler_input):
        return self._permission.ask_profile_setup(handler_input)
