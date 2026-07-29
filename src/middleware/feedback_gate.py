from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.services.feedback import feedback_service


class FeedbackGateHandler(AbstractRequestHandler):
    def can_handle(self, handler_input) -> bool:
        return feedback_service.should_block(handler_input)

    def handle(self, handler_input):
        return feedback_service.pending_response(handler_input)
