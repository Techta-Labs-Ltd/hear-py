from __future__ import annotations
from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from src.services.feedback import clear_feedback
from src.services.following import is_following
from src.services.listening import record_listening_event
from src.services.store import get_store, update_store
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import (
    ssml,
    is_bad_credit,
    WELCOME_REPROMPT,
    FEEDBACK_FOLLOW_ASK,
    FEEDBACK_FOLLOW_REPROMPT,
    FEEDBACK_ENJOYED_ALREADY_FOLLOWING,
    FEEDBACK_FOLLOW_DECLINED,
)
from src.services.feedback import submit_feedback
from src.services.deferred_intent import has_deferred_intent, resume_deferred_intent
from src.utils.feedback_flow import idle_next_response
from src.utils.speech import FEEDBACK_SOMEWHAT
from src.services.feedback import dismiss_feedback_prompt
from src.utils.speech import (
    FEEDBACK_NOT_ENJOYED,
    FEEDBACK_REPORT_REPROMPT,
)
from src.services.dialog_state import activate_dialog
from src.utils.playback_context import snapshot_report_context
from src.utils.normalize_content_item import pick_content_source
from src.utils.speech import FEEDBACK_SKIP_INTRO
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

        pending = dict(store.get("pendingFeedback") or {})
        await submit_feedback(handler_input, "enjoyed")

        record_listening_event(
            handler_input,
            category=pending.get("category") or store.get("feedbackCategory"),
            creator=pending.get("creatorName") or store.get("feedbackCreator"),
            liked=True,
        )

        selected_source = pick_content_source({
            "organizationId": pending.get("organizationId"),
            "organizationName": pending.get("organizationName"),
            "creatorId": pending.get("creatorId") or store.get("feedbackCreatorId"),
            "creatorName": pending.get("creatorName") or store.get("feedbackCreator"),
        }) or {}
        creator_id = selected_source.get("id")
        creator_name = selected_source.get("name")
        source_type = selected_source.get("kind") or "creator"

        update_store(handler_input, {
            "awaitingFollow": False,
            "pendingFollowSource": None,
        })
        if has_deferred_intent(handler_input):
            await clear_feedback(handler_input)
            return await resume_deferred_intent(handler_input)

        updated_store = get_store(handler_input)
        if (
            creator_id
            and creator_name
            and not is_bad_credit(creator_name)
            and not is_following(updated_store, creator_id, source_type)
        ):
            update_store(handler_input, {
                "awaitingFollow": True,
                "pendingFollowSource": {
                    "id": creator_id,
                    "name": creator_name,
                    "type": source_type,
                },
            })
            ask = FEEDBACK_FOLLOW_ASK(creator_name)
            return handler_input.response_builder \
                .speak(ssml(ask)) \
                .reprompt(ssml(FEEDBACK_FOLLOW_REPROMPT(creator_name))) \
                .set_should_end_session(False) \
                .response

        await clear_feedback(handler_input)
        title = pending.get("title") or store.get("feedbackContentTitle") or store.get("currentContentTitle")
        already_msg = FEEDBACK_ENJOYED_ALREADY_FOLLOWING(title, creator_name) \
            if (title or creator_name) else FEEDBACK_FOLLOW_DECLINED
        return idle_next_response(handler_input, already_msg)

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

        pending = dict(store.get("pendingFeedback") or {})
        await submit_feedback(handler_input, "somewhat")
        record_listening_event(
            handler_input,
            category=pending.get("category") or store.get("feedbackCategory"),
            creator=pending.get("creatorName") or store.get("feedbackCreator"),
            liked=None,
        )

        await clear_feedback(handler_input)
        if has_deferred_intent(handler_input):
            return await resume_deferred_intent(handler_input)
        return idle_next_response(handler_input, FEEDBACK_SOMEWHAT)

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

        pending = dict(store.get("pendingFeedback") or {})
        await submit_feedback(handler_input, "not_enjoyed")

        record_listening_event(
            handler_input,
            category=pending.get("category") or store.get("feedbackCategory"),
            creator=pending.get("creatorName") or store.get("feedbackCreator"),
            liked=False,
        )

        report_context = snapshot_report_context(store)
        dismiss_feedback_prompt(handler_input)
        update_store(handler_input, {
            "awaitingReportDecision": True,
            "reportContext": report_context,
        })
        activate_dialog(
            handler_input,
            "report_decision",
            context=report_context,
            deferred_request=(
                get_store(handler_input).get("deferredIntent")
                if has_deferred_intent(handler_input)
                else None
            ),
        )

        return handler_input.response_builder \
            .speak(ssml(FEEDBACK_NOT_ENJOYED)) \
            .reprompt(ssml(FEEDBACK_REPORT_REPROMPT)) \
            .set_should_end_session(False) \
            .response

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
            if has_deferred_intent(handler_input):
                return await resume_deferred_intent(handler_input)
            return idle_next_response(handler_input, FEEDBACK_SKIP_INTRO)

        if not store.get("awaitingFeedback"):
            return handler_input.response_builder \
                .speak(ssml(WELCOME_REPROMPT)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        await submit_feedback(handler_input, "skipped")
        await clear_feedback(handler_input)
        if has_deferred_intent(handler_input):
            return await resume_deferred_intent(handler_input)
        return idle_next_response(handler_input, FEEDBACK_SKIP_INTRO)
