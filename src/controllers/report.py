from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.context import RequestContext
from src.alexa.dialog import DeferredIntentManager, DialogStateManager
from src.alexa.feedback import AlexaFeedback
from src.alexa.feedback_response import FeedbackContinuation
from src.alexa.feedback_service import FeedbackService
from src.alexa.playback_context import PlaybackContext
from src.alexa.playback_controls import PlaybackControls
from src.alexa.playback_details import PlaybackDetails
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.report import Report, ReportCommand
from src.models.user import User
from src.services.logging_control import ApplicationLog


def _stage_report_event(handler_input, events, receipt, store: dict) -> None:
    """Bridge a framework-free report receipt into the request-bound outbox."""
    request = RequestContext.bind(handler_input)
    if not request.alexa_user_id:
        return
    events.report(
        handler_input=handler_input,
        alexa_user_id=request.alexa_user_id,
        listener_id=store.get("listenerId"),
        report=receipt.event_payload(),
    )


class ReportContentHandler(AbstractRequestHandler):
    """Flags the currently playing content for review."""

    def __init__(
        self,
        user: User,
        reports: Report,
        feedback: FeedbackService,
        playback_controls: PlaybackControls,
        events,
    ) -> None:
        self._user = user
        self._reports = reports
        self._feedback = feedback
        self._playback_controls = playback_controls
        self._events = events

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "ReportContentIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        store = self._user.snapshot(handler_input)
        audio = PlaybackContext.read_audio_player_context(handler_input)
        report = Report.build_report_context(
            store, audio_token=audio.get("token") if audio else None
        )
        content_id = report.get("contentId")
        if not content_id:
            ApplicationLog.warning("Hear: report content blocked contentIdPresent=false")
            return handler_input.response_builder.speak(Speech.REPORT_NOTHING_PLAYING).response
        try:
            receipt = self._reports.record_report(
                ReportCommand(
                    subject_type="content",
                    subject_id=str(content_id),
                    subject_name=report.get("title"),
                    content_id=str(content_id),
                    publication_id=report.get("publicationId"),
                )
            )
            _stage_report_event(handler_input, self._events, receipt, store)
            self._user.update(
                handler_input, {"awaitingReportDecision": False, "reportContext": None}
            )
            DialogStateManager.clear(handler_input, "report_decision")
            if DeferredIntentManager.has(handler_input):
                return await DeferredIntentManager.resume(handler_input)
            return await self._present_continue_question(handler_input, report, store)
        except Exception as err:
            ApplicationLog.warning("Report content error=%s", type(err).__name__)
            return (
                handler_input.response_builder.speak(Speech.ERROR_GENERIC)
                .reprompt(Speech.WELCOME_REPROMPT)
                .set_should_end_session(False)
                .response
            )

    async def _present_continue_question(
        self,
        handler_input: HandlerInput,
        report: dict,
        store: dict,
    ):
        if not report.get("requested") and report.get("discoveryContext"):
            await self._feedback.clear(handler_input)
            continuation = FeedbackContinuation.present(
                handler_input,
                report,
                store,
                Speech.REPORT_CONTENT_CONFIRM,
                self._user,
            )
            if continuation:
                return continuation
        self._user.update(handler_input, {"awaitingContinueAfterFlag": True})
        directive = await self._playback_controls.pause_active(handler_input)
        question = AlexaFeedback.keep_listening_question(report, store)
        reprompt = AlexaFeedback.keep_listening_reprompt(report, store)
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(f"{Speech.REPORT_CONTENT_CONFIRM} {question}")
            )
            .reprompt(Ssml.ssml(reprompt))
            .add_directive(directive)
            .set_should_end_session(False)
            .response
        )


class ReportCreatorHandler(AbstractRequestHandler):
    def __init__(self, user: User, reports: Report, feedback: FeedbackService, events) -> None:
        self._user = user
        self._reports = reports
        self._feedback = feedback
        self._events = events

    "Flags the currently playing content's creator for review."

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "ReportCreatorIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        store = self._user.snapshot(handler_input)
        creator_id = store.get("currentCreatorId") or store.get("feedbackCreatorId")
        creator_name = store.get("currentCreator") or store.get("feedbackCreator")
        if not creator_id:
            return handler_input.response_builder.speak(Speech.REPORT_NOTHING_PLAYING).response
        try:
            receipt = self._reports.record_report(
                ReportCommand(
                    subject_type="creator",
                    subject_id=str(creator_id),
                    subject_name=creator_name,
                    content_id=store.get("currentContentId") or store.get("feedbackContentId"),
                    publication_id=store.get("currentPublicationId"),
                )
            )
            _stage_report_event(handler_input, self._events, receipt, store)
            await self._feedback.clear(handler_input)
            confirm = (
                Speech.REPORT_CREATOR_CONFIRM(creator_name)
                if creator_name and (not Speech.is_bad_credit(creator_name))
                else "Thank you. We've flagged that creator's content for review. What would you like to listen to next?"
            )
            return AlexaResponse.present_idle_next(handler_input, confirm)
        except Exception as err:
            ApplicationLog.warning("Report creator error=%s", type(err).__name__)
            return (
                handler_input.response_builder.speak(Speech.ERROR_GENERIC)
                .reprompt(Speech.WELCOME_REPROMPT)
                .set_should_end_session(False)
                .response
            )


class WhatsThisAboutHandler(AbstractRequestHandler):
    """Describes what the currently playing content is about."""

    def __init__(self, details: PlaybackDetails) -> None:
        self._details = details

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "WhatsThisAboutIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._details.about(handler_input)
