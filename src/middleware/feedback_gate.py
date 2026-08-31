from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.alexa.feedback import AlexaFeedback


class FeedbackGateHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input) -> bool:
        return self._deps.feedback.should_block(handler_input)

    def handle(self, handler_input):
        return AlexaFeedback.present_pending_feedback(
            handler_input, self._deps.user.snapshot(handler_input)
        )
