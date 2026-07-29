from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.services.storage.persistence import (
    get_store, update_store, mark_feedback_given_from_store,
    record_listening_event, dismiss_feedback_prompt,
)
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import (
    ssml, WELCOME_REPROMPT, FEEDBACK_NOT_ENJOYED, FEEDBACK_REPORT_REPROMPT,
)
from src.services.feedback.candidates import submit_feedback
from src.utils.playback_context import snapshot_report_context


class FeedbackNotEnjoyedHandler(AbstractRequestHandler):
    """Handles the FeedbackNotEnjoyedIntent — records dislike and offers reporting."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "FeedbackNotEnjoyedIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        store = get_store(handler_input)

        if not store.get("awaitingFeedback"):
            return handler_input.response_builder \
                .speak(ssml(WELCOME_REPROMPT)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        await submit_feedback(handler_input, "not_enjoyed")

        record_listening_event(handler_input, {
            "category": store.get("feedbackCategory"),
            "creator": store.get("feedbackCreator"),
            "liked": False,
        })

        report_context = snapshot_report_context(store)
        dismiss_feedback_prompt(handler_input)
        update_store(handler_input, {
            "awaitingReportDecision": True,
            "reportContext": report_context,
        })

        return handler_input.response_builder \
            .speak(ssml(FEEDBACK_NOT_ENJOYED)) \
            .reprompt(ssml(FEEDBACK_REPORT_REPROMPT)) \
            .set_should_end_session(False) \
            .response
