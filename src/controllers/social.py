from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.request import AlexaRequest
from src.models.social import CreatorIdentity, FollowCreator, UnfollowCreator


class WhoIsCreatorHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._action = CreatorIdentity(deps=deps)

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "WhoIsCreatorIntent"
        )

    def handle(self, handler_input: HandlerInput):
        return self._action.execute(handler_input)


class FollowCreatorHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._action = FollowCreator(deps=deps)

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "FollowCreatorIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(handler_input)


class UnfollowCreatorHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._action = UnfollowCreator(deps=deps)

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "UnfollowCreatorIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(handler_input)
