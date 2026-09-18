from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.alexa.context import RequestContext
from src.alexa.feedback import AlexaFeedback
from src.alexa.feedback_response import SkipFeedback
from src.alexa.feedback_service import FeedbackService
from src.alexa.request import AlexaRequest
from src.models.user import User


class FeedbackGateHandler(AbstractRequestHandler):
    def __init__(self, feedback: FeedbackService, user: User) -> None:
        self._feedback = feedback
        self._user = user

    def can_handle(self, handler_input) -> bool:
        return self._feedback.should_block(handler_input)

    def handle(self, handler_input):
        return AlexaFeedback.present_pending_feedback(
            handler_input, self._user.snapshot(handler_input)
        )


class FeedbackSkipGateHandler(AbstractRequestHandler):
    def __init__(self, user: User, skip_feedback: SkipFeedback) -> None:
        self._user = user
        self._skip_feedback = skip_feedback

    def can_handle(self, handler_input) -> bool:
        store = self._user.snapshot(handler_input)
        return bool(
            AlexaRequest.get_intent_name(handler_input)
            in {"AMAZON.SkipIntent", "AMAZON.NextIntent"}
            and (
                store.get("awaitingFeedback")
                or store.get("awaitingReportDecision")
                or store.get("awaitingFeedbackContinuation")
            )
        )

    async def handle(self, handler_input):
        return await self._skip_feedback.execute(RequestContext.bind(handler_input))
