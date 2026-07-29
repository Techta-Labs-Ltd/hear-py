from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.services.storage.persistence import (
    get_store, clear_feedback, mark_feedback_given_from_store, record_listening_event,
)
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import ssml, WELCOME_REPROMPT, FEEDBACK_SOMEWHAT
from src.services.feedback.candidates import submit_feedback
from src.services.deferred_intent import (
    has_deferred_intent,
    resume_deferred_intent,
)
from src.utils.feedback_flow import idle_next_response


class FeedbackSomewhatHandler(AbstractRequestHandler):
    """Handles the FeedbackSomewhatIntent — records neutral feedback."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "FeedbackSomewhatIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        store = get_store(handler_input)

        if not store.get("awaitingFeedback"):
            return handler_input.response_builder \
                .speak(ssml(WELCOME_REPROMPT)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        await submit_feedback(handler_input, "somewhat")
        record_listening_event(
            handler_input,
            category=store.get("feedbackCategory"),
            creator=store.get("feedbackCreator"),
            liked=None,
        )

        await clear_feedback(handler_input)
        if has_deferred_intent(handler_input):
            return await resume_deferred_intent(handler_input)
        return idle_next_response(handler_input, FEEDBACK_SOMEWHAT)
