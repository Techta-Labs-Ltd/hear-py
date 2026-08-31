from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.playback_context import PlaybackContext
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.dialog import DeferredIntentManager, DialogStateManager
from src.models.report import Report


class ReportModule:
    logger = logging.getLogger(__name__)


class ReportContentHandler(AbstractRequestHandler):
    """Flags the currently playing content for review."""

    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "ReportContentIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        store = self._deps.user.snapshot(handler_input)
        audio = PlaybackContext.read_audio_player_context(handler_input)
        report = Report.build_report_context(
            store, audio_token=audio.get("token") if audio else None
        )
        content_id = report.get("contentId")
        if not content_id:
            ReportModule.logger.warning("Hear: report content blocked contentId=%s", content_id)
            return handler_input.response_builder.speak(Speech.REPORT_NOTHING_PLAYING).response
        try:
            await self._deps.reports.record_report(
                handler_input,
                {
                    "type": "content",
                    "id": str(content_id),
                    "name": report.get("title"),
                    "contentId": str(content_id),
                    "publicationId": report.get("publicationId"),
                },
            )
            self._deps.user.update(
                handler_input, {"awaitingReportDecision": False, "reportContext": None}
            )
            DialogStateManager.clear(handler_input, "report_decision")
            if DeferredIntentManager.has(handler_input):
                return await DeferredIntentManager.resume(handler_input)
            self._deps.user.update(handler_input, {"awaitingContinueAfterFlag": True})
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(Speech.REPORT_CONTENT_THEN_ASK_CONTINUE)
                )
                .reprompt(Speech.FLAGGED_CONTINUE_REPROMPT)
                .set_should_end_session(False)
                .response
            )
        except Exception as err:
            ReportModule.logger.warning("Report content error: %s", err)
            return (
                handler_input.response_builder.speak(Speech.ERROR_GENERIC)
                .reprompt(Speech.WELCOME_REPROMPT)
                .set_should_end_session(False)
                .response
            )


class ReportCreatorHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    "Flags the currently playing content's creator for review."

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "ReportCreatorIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        store = self._deps.user.snapshot(handler_input)
        creator_id = store.get("currentCreatorId") or store.get("feedbackCreatorId")
        creator_name = store.get("currentCreator") or store.get("feedbackCreator")
        if not creator_id:
            return handler_input.response_builder.speak(Speech.REPORT_NOTHING_PLAYING).response
        try:
            await self._deps.reports.record_report(
                handler_input,
                {
                    "type": "creator",
                    "id": str(creator_id),
                    "name": creator_name,
                    "contentId": store.get("currentContentId") or store.get("feedbackContentId"),
                    "publicationId": store.get("currentPublicationId"),
                },
            )
            await self._deps.feedback.clear(handler_input)
            confirm = (
                Speech.REPORT_CREATOR_CONFIRM(creator_name)
                if creator_name and (not Speech.is_bad_credit(creator_name))
                else "Thank you. We've flagged that creator's content for review. What would you like to listen to next?"
            )
            return AlexaResponse.present_idle_next(handler_input, confirm)
        except Exception as err:
            ReportModule.logger.warning("Report creator error: %s", err)
            return (
                handler_input.response_builder.speak(Speech.ERROR_GENERIC)
                .reprompt(Speech.WELCOME_REPROMPT)
                .set_should_end_session(False)
                .response
            )


class WhatsThisAboutHandler(AbstractRequestHandler):
    """Describes what the currently playing content is about."""

    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "WhatsThisAboutIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        store = self._deps.user.snapshot(handler_input)
        summary = store.get("currentSummary")
        title = store.get("currentContentTitle") or store.get("feedbackContentTitle")
        creator = store.get("currentCreator") or store.get("feedbackCreator")
        if creator and Speech.is_bad_credit(creator):
            creator = None
        phrase = Speech.CONTENT_ABOUT_PHRASE(title, summary, None, creator)
        card_title = str(title or "Current recording")
        card_lines = []
        if creator:
            card_lines.append(f"By {creator}")
        if summary:
            card_lines.append(str(summary))
        builder = handler_input.response_builder.speak(Ssml.ssml(phrase))
        if card_lines:
            builder = builder.with_simple_card(card_title, "\n\n".join(card_lines))
        return builder.response
