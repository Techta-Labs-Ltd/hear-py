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
from src.alexa.feedback_service import FeedbackService
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.user import User
from src.services.logging_control import ApplicationLog


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
        feedback = AlexaFeedback.normalize_slot(
            AlexaRequest.get_slot(handler_input, "feedback")
        )
        action = self._actions.get(feedback) if feedback else None
        if action and hasattr(action, "execute"):
            return await action.execute(request)
        store = User.snapshot(handler_input)
        if not store.get("awaitingFeedback"):
            return AlexaFeedback.present_pending_feedback(handler_input, store)
        spoken = AlexaRequest.get_spoken_slot_value(AlexaRequest.get_slot(handler_input, "feedback"))
        ApplicationLog.info("Hear: feedback answer unmatched heard=%r", str(spoken or "")[:40])
        if FeedbackService.note_unrecognised_answer(handler_input):
            return AlexaResponse.present_idle_next(
                handler_input, Speech.FEEDBACK_GIVEN_UP, Speech.WELCOME_REPROMPT
            )
        title = Speech.escape_ssml_lite(AlexaFeedback.subject_title(store.get("pendingFeedback") or {}, store))
        retry = Speech.FEEDBACK_YES_NO_RETRY(title)
        return (
            handler_input.response_builder.speak(Ssml.ssml(retry))
            .reprompt(Ssml.ssml(retry))
            .set_should_end_session(False)
            .response
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
