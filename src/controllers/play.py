from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.request import AlexaRequest
from src.models.play import PlayContent, PlayCreator, PlayOrganization


class PlayContentHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._action = PlayContent(deps=deps)

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return AlexaRequest.get_request_type(
            handler_input
        ) == "IntentRequest" and AlexaRequest.get_intent_name(handler_input) in {
            "PlayContentIntent",
            "PlayLatestContentIntent",
            "PlayPublicationIntent",
        }

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(handler_input)


class PlayByCreatorHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._action = PlayCreator(deps=deps)

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "PlayByCreatorIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(handler_input)


class PlayByOrganizationHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._action = PlayOrganization(deps=deps)

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "PlayByOrganizationIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(handler_input)
