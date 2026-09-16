from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.context import RequestContext
from src.alexa.feedback import AlexaFeedback
from src.alexa.feedback_response import (
    EnjoyedFeedback,
    NotEnjoyedFeedback,
    RatingRequest,
    SkipFeedback,
    SomewhatFeedback,
)
from src.alexa.request import AlexaRequest
from src.models.user import User


class RateContentHandler(AbstractRequestHandler):
    def __init__(self, action: RatingRequest) -> None:
        self._action = action

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "RateContentIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(RequestContext.bind(handler_input))


class FeedbackEnjoyedHandler(AbstractRequestHandler):
    def __init__(self, action: EnjoyedFeedback) -> None:
        self._action = action

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "FeedbackEnjoyedIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(RequestContext.bind(handler_input))


class FeedbackSomewhatHandler(AbstractRequestHandler):
    def __init__(self, action: SomewhatFeedback) -> None:
        self._action = action

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "FeedbackSomewhatIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(RequestContext.bind(handler_input))


class FeedbackNotEnjoyedHandler(AbstractRequestHandler):
    def __init__(self, action: NotEnjoyedFeedback) -> None:
        self._action = action

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "FeedbackNotEnjoyedIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(RequestContext.bind(handler_input))


class FeedbackResponseHandler(AbstractRequestHandler):
    def __init__(
        self,
        enjoyed: EnjoyedFeedback,
        somewhat: SomewhatFeedback,
        not_enjoyed: NotEnjoyedFeedback,
        skipped: SkipFeedback,
    ) -> None:
        self._actions = {
            "enjoyed": enjoyed,
            "somewhat": somewhat,
            "not enjoyed": not_enjoyed,
            "skipped": skipped,
        }

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "FeedbackResponseIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        request = RequestContext.bind(handler_input)
        feedback = AlexaFeedback.normalize_value(
            AlexaRequest.get_slot_value(handler_input, "feedback")
        )
        action = self._actions.get(feedback) if feedback else None
        if action and hasattr(action, "execute"):
            return await action.execute(request)
        return AlexaFeedback.present_pending_feedback(
            handler_input, User.snapshot(handler_input)
        )


class SkipFeedbackHandler(AbstractRequestHandler):
    def __init__(self, action: SkipFeedback) -> None:
        self._action = action

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "SkipFeedbackIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(RequestContext.bind(handler_input))
