from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from src.alexa.intent_dispatch import IntentDispatcher


class IntentDispatchGateHandler(AbstractRequestHandler):
    def __init__(self, dispatcher: IntentDispatcher) -> None:
        self._dispatcher = dispatcher

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return self._dispatcher.can_dispatch(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        return self._dispatcher.dispatch(handler_input)
