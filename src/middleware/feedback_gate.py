from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.services.feedback import feedback_service
from src.services.deferred_intent import capture_deferred_intent


class FeedbackGateHandler(AbstractRequestHandler):
    def can_handle(self, handler_input) -> bool:
        return feedback_service.should_block(handler_input)

    def handle(self, handler_input):
        capture_deferred_intent(handler_input)
        return feedback_service.pending_response(handler_input)
