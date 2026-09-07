from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.feedback import AlexaFeedback
from src.alexa.request import AlexaRequest
from src.models.feedback_response import (
    EnjoyedFeedback,
    NotEnjoyedFeedback,
    RatingRequest,
    SkipFeedback,
    SomewhatFeedback,
)


class RateContentHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._action = RatingRequest(deps=deps)

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "RateContentIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(handler_input)


class FeedbackEnjoyedHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._action = EnjoyedFeedback(deps=deps)

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "FeedbackEnjoyedIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(handler_input)


class FeedbackSomewhatHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._action = SomewhatFeedback(deps=deps)

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "FeedbackSomewhatIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(handler_input)


class FeedbackNotEnjoyedHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._action = NotEnjoyedFeedback(deps=deps)

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "FeedbackNotEnjoyedIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(handler_input)


class FeedbackResponseHandler(AbstractRequestHandler):
    ACTIONS = {
        "enjoyed": EnjoyedFeedback,
        "somewhat": SomewhatFeedback,
        "not enjoyed": NotEnjoyedFeedback,
    }

    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "FeedbackResponseIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        feedback = AlexaFeedback.normalize_value(
            AlexaRequest.get_slot_value(handler_input, "feedback")
        )
        action_type = FeedbackResponseHandler.ACTIONS.get(feedback)
        if action_type:
            return await action_type(deps=self._deps).execute(handler_input)
        if feedback == "skipped":
            return await SkipFeedback(deps=self._deps).execute(handler_input)
        return AlexaFeedback.present_pending_feedback(
            handler_input, self._deps.user.snapshot(handler_input)
        )


class SkipFeedbackHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._action = SkipFeedback(deps=deps)

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "SkipFeedbackIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(handler_input)
