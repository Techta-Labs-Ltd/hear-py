from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.services.persistence import (
    get_store, update_store, is_following, clear_feedback,
    dismiss_feedback_prompt, mark_feedback_given_from_store, record_listening_event,
)
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import (
    ssml, is_bad_credit, WELCOME_REPROMPT, FEEDBACK_FOLLOW_ASK,
    FEEDBACK_FOLLOW_REPROMPT, FEEDBACK_ENJOYED_ALREADY_FOLLOWING,
    FEEDBACK_FOLLOW_DECLINED,
)
from src.utils.listen_tracker import save_feedback_with_listen_context
from src.utils.feedback_flow import idle_next_response


class FeedbackEnjoyedHandler(AbstractRequestHandler):
    """Handles the FeedbackEnjoyedIntent — records liked feedback and offers to follow the creator."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "FeedbackEnjoyedIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        store = get_store(handler_input)

        if not store.get("awaitingFeedback"):
            return handler_input.response_builder \
                .speak(ssml(WELCOME_REPROMPT)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        if store.get("feedbackContentId"):
            await save_feedback_with_listen_context(handler_input, "enjoyed")

        mark_feedback_given_from_store(handler_input, store)
        record_listening_event(handler_input, {
            "category": store.get("feedbackCategory"),
            "creator": store.get("feedbackCreator"),
            "liked": True,
        })

        creator_id = store.get("feedbackCreatorId")
        creator_name = store.get("feedbackCreator")

        dismiss_feedback_prompt(handler_input)
        update_store(handler_input, {
            "awaitingFollow": False,
            "awaitingNotificationOptIn": False,
        })

        updated_store = get_store(handler_input)
        if (
            creator_id
            and creator_name
            and not is_bad_credit(creator_name)
            and not is_following(updated_store, creator_id)
        ):
            update_store(handler_input, {"awaitingFollow": True})
            ask = FEEDBACK_FOLLOW_ASK(creator_name)
            return handler_input.response_builder \
                .speak(ssml(ask)) \
                .reprompt(ssml(FEEDBACK_FOLLOW_REPROMPT(creator_name))) \
                .set_should_end_session(False) \
                .response

        await clear_feedback(handler_input)
        title = store.get("feedbackContentTitle") or store.get("currentContentTitle")
        already_msg = FEEDBACK_ENJOYED_ALREADY_FOLLOWING(title, creator_name) \
            if (title or creator_name) else FEEDBACK_FOLLOW_DECLINED
        return idle_next_response(handler_input, already_msg)
