from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from src.services.feedback import clear_feedback
from src.services.store import get_store, update_store
from src.utils.skill_request import (
    get_request_type,
    get_intent_name,
)
from src.utils.speech import (
    ssml,
    is_bad_credit,
    REPORT_NOTHING_PLAYING,
    REPORT_CONTENT_THEN_ASK_CONTINUE,
    FLAGGED_CONTINUE_REPROMPT,
    REPORT_CREATOR_CONFIRM,
    CONTENT_ABOUT_PHRASE,
    ERROR_GENERIC,
    WELCOME_REPROMPT,
)
from src.utils.feedback_flow import idle_next_response
from src.utils.playback_context import read_audio_player_context, build_report_context
from src.services.deferred_intent import has_deferred_intent, resume_deferred_intent
from src.services.dialog_state import clear_active_dialog
class ReportContentHandler(AbstractRequestHandler):
    """Flags the currently playing content for review."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "ReportContentIntent"
        )

    async def handle(self, handler_input: HandlerInput):

        store = get_store(handler_input)
        audio = read_audio_player_context(handler_input)
        report = build_report_context(
            store,
            audio_token=audio.get("token") if audio else None,
        )
        content_id = report.get("contentId")

        if not content_id:
            logger.warning(
                "Hear: report content blocked contentId=%s", content_id,
            )
            return handler_input.response_builder \
                .speak(REPORT_NOTHING_PLAYING) \
                .response

        try:
            update_store(handler_input, {
                "awaitingReportDecision": False,
                "reportContext": None,
            })
            clear_active_dialog(handler_input, "report_decision")
            if has_deferred_intent(handler_input):
                return await resume_deferred_intent(handler_input)
            update_store(handler_input, {"awaitingContinueAfterFlag": True})
            return handler_input.response_builder \
                .speak(ssml(REPORT_CONTENT_THEN_ASK_CONTINUE)) \
                .reprompt(FLAGGED_CONTINUE_REPROMPT) \
                .set_should_end_session(False) \
                .response
        except Exception as err:
            logger.warning("Report content error: %s", err)
            return handler_input.response_builder \
                .speak(ERROR_GENERIC) \
                .reprompt(WELCOME_REPROMPT) \
                .set_should_end_session(False) \
                .response


class ReportCreatorHandler(AbstractRequestHandler):
    """Flags the currently playing content's creator for review."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "ReportCreatorIntent"
        )

    async def handle(self, handler_input: HandlerInput):

        store = get_store(handler_input)
        creator_id = store.get("currentCreatorId") or store.get("feedbackCreatorId")
        creator_name = store.get("currentCreator") or store.get("feedbackCreator")

        if not creator_id:
            return handler_input.response_builder \
                .speak(REPORT_NOTHING_PLAYING) \
                .response

        try:
            await clear_feedback(handler_input)

            confirm = REPORT_CREATOR_CONFIRM(creator_name) \
                if (creator_name and not is_bad_credit(creator_name)) \
                else "Thank you. We've flagged that creator's content for review. What would you like to listen to next?"

            return idle_next_response(handler_input, confirm)
        except Exception as err:
            logger.warning("Report creator error: %s", err)
            return handler_input.response_builder \
                .speak(ERROR_GENERIC) \
                .reprompt(WELCOME_REPROMPT) \
                .set_should_end_session(False) \
                .response


class WhatsThisAboutHandler(AbstractRequestHandler):
    """Describes what the currently playing content is about."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "WhatsThisAboutIntent"
        )

    async def handle(self, handler_input: HandlerInput):

        store = get_store(handler_input)
        summary = store.get("currentSummary")
        title = store.get("currentContentTitle") or store.get("feedbackContentTitle")
        creator = store.get("currentCreator") or store.get("feedbackCreator")

        if creator and is_bad_credit(creator):
            creator = None

        phrase = CONTENT_ABOUT_PHRASE(title, summary, None, creator)
        return handler_input.response_builder \
            .speak(ssml(phrase)) \
            .response
