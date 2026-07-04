from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.services.persistence import get_store
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.feedback_gate import block_if_awaiting_feedback, enforce_interaction_gate


def _should_run_feedback_gate(handler_input: HandlerInput) -> bool:
    """Determine if the feedback gate should be evaluated for this request."""
    rt = get_request_type(handler_input)
    if isinstance(rt, str) and rt.startswith("AudioPlayer."):
        return False
    if rt == "SessionEndedRequest":
        return False
    if rt == "IntentRequest":
        intent = get_intent_name(handler_input)
        if intent in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
            return False
    store = get_store(handler_input)
    if store and store.get("onboardingStage") == "ask_town":
        return False
    return True


def _resolve_gate_response(handler_input: HandlerInput):
    """Try all gate checks and return the first blocking response, or None."""
    return block_if_awaiting_feedback(handler_input) or enforce_interaction_gate(handler_input)


class FeedbackGateHandler(AbstractRequestHandler):
    """Gate handler that blocks intents when feedback is pending."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        if not _should_run_feedback_gate(handler_input):
            return False
        return bool(_resolve_gate_response(handler_input))

    def handle(self, handler_input: HandlerInput):
        return _resolve_gate_response(handler_input)
