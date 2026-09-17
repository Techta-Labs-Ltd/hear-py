from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from src.alexa.availability import Availability
from src.alexa.dialog import DialogStateManager
from src.alexa.request import AlexaRequest
from src.constants.availability import AvailabilityConstants


class AvailabilityDialogHandler(AbstractRequestHandler):
    def __init__(self, availability: Availability) -> None:
        self._availability = availability

    def can_handle(self, handler_input: HandlerInput) -> bool:
        active = DialogStateManager.get_active(handler_input) or {}
        return bool(
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and active.get("type") == AvailabilityConstants.DIALOG_TYPE
            and AlexaRequest.get_intent_name(handler_input)
            not in AvailabilityConstants.EXIT_INTENTS
            | AvailabilityConstants.PASSTHROUGH_INTENTS
        )

    async def handle(self, handler_input: HandlerInput) -> Response:
        return await self._availability.handle_dialog(handler_input)
