from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.alexa.request import AlexaRequest


class HearNotificationsHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None) -> None:
        self._notifications = deps.notifications

    def can_handle(self, handler_input) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "HearNotificationsIntent"
        )

    async def handle(self, handler_input):
        return await self._notifications.offer(handler_input, explicit=True)


class EnableNotificationsHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None) -> None:
        self._notifications = deps.notifications

    def can_handle(self, handler_input) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "EnableNotificationsIntent"
        )

    def handle(self, handler_input):
        return self._notifications.enable(handler_input)


class DisableNotificationsHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None) -> None:
        self._notifications = deps.notifications

    def can_handle(self, handler_input) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "DisableNotificationsIntent"
        )

    def handle(self, handler_input):
        return self._notifications.disable(handler_input)
