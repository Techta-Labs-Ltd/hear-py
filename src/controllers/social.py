from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.social import CreatorIdentity, FollowCreator, UnfollowCreator


class WhoIsCreatorHandler(AbstractRequestHandler):
    def __init__(self, action: CreatorIdentity) -> None:
        self._action = action

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "WhoIsCreatorIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(RequestContext.bind(handler_input))


class FollowCreatorHandler(AbstractRequestHandler):
    def __init__(self, action: FollowCreator) -> None:
        self._action = action

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "FollowCreatorIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(RequestContext.bind(handler_input))


class UnfollowCreatorHandler(AbstractRequestHandler):
    def __init__(self, action: UnfollowCreator) -> None:
        self._action = action

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "UnfollowCreatorIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(RequestContext.bind(handler_input))
