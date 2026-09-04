from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from src.alexa.request import AlexaRequest
from src.constants.availability import AvailabilityConstants
from src.models.dialog import DialogStateManager


class AvailabilityDialogHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None) -> None:
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        active = DialogStateManager.get_active(handler_input) or {}
        return bool(
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and active.get("type") == AvailabilityConstants.DIALOG_TYPE
            and AlexaRequest.get_intent_name(handler_input)
            not in AvailabilityConstants.EXIT_INTENTS
        )

    async def handle(self, handler_input: HandlerInput) -> Response:
        return await self._deps.availability.handle_dialog(handler_input)
