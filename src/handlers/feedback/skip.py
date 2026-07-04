from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.services.persistence import get_store, clear_feedback, mark_feedback_given_from_store
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import ssml, WELCOME_REPROMPT, FEEDBACK_SKIP_INTRO
from src.utils.feedback_flow import idle_next_response


class SkipFeedbackHandler(AbstractRequestHandler):
    """Handles the SkipFeedbackIntent — skips feedback without rating."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "SkipFeedbackIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        store = get_store(handler_input)

        if store.get("awaitingReportDecision"):
            await clear_feedback(handler_input)
            return idle_next_response(handler_input, FEEDBACK_SKIP_INTRO)

        if not store.get("awaitingFeedback"):
            return handler_input.response_builder \
                .speak(ssml(WELCOME_REPROMPT)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        mark_feedback_given_from_store(handler_input, store)
        await clear_feedback(handler_input)
        return idle_next_response(handler_input, FEEDBACK_SKIP_INTRO)
