from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.alexa.feedback import AlexaFeedback
from src.alexa.request import AlexaRequest
from src.models.feedback_response import SkipFeedback


class FeedbackGateHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input) -> bool:
        return self._deps.feedback.should_block(handler_input)

    def handle(self, handler_input):
        return AlexaFeedback.present_pending_feedback(
            handler_input, self._deps.user.snapshot(handler_input)
        )


class FeedbackSkipGateHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input) -> bool:
        store = self._deps.user.snapshot(handler_input)
        return bool(
            AlexaRequest.get_intent_name(handler_input)
            in {"AMAZON.SkipIntent", "AMAZON.NextIntent"}
            and (store.get("awaitingFeedback") or store.get("awaitingReportDecision"))
        )

    async def handle(self, handler_input):
        return await SkipFeedback(deps=self._deps).execute(handler_input)
