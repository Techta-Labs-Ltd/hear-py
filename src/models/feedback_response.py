from __future__ import annotations

from ask_sdk_core.handler_input import HandlerInput

from src.alexa.feedback import AlexaFeedback
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.dialog import DeferredIntentManager, DialogStateManager
from src.models.feedback import FeedbackService
from src.models.playback_controls import PlaybackControls
from src.models.report import Report
from src.models.social import FollowingManager, ListeningTracker
from src.models.user import User
from src.utils.content import ContentUtils


class RatingRequest:
    def __init__(self, *, deps: object | None = None):
        self._deps = Feedback._dependencies(deps)

    async def execute(self, handler_input: HandlerInput):
        pending = self._deps.feedback.request_current_rating(handler_input)
        if pending:
            return AlexaFeedback.present_requested_feedback(handler_input)
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.RATE_CONTENT_NOTHING))
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )


class EnjoyedFeedback:
    def __init__(self, *, deps: object | None = None):
        self._deps = Feedback._dependencies(deps)

    async def execute(self, handler_input: HandlerInput):
        store = User.snapshot(handler_input)
        if not store.get("awaitingFeedback"):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        pending = dict(store.get("pendingFeedback") or {})
        await self._deps.feedback.submit(handler_input, "enjoyed")
        selected_source = Feedback._feedback_source(pending, store)
        ListeningTracker.record(
            handler_input,
            category=pending.get("category") or store.get("feedbackCategory"),
            creator=selected_source.get("name"),
            liked=True,
        )
        if pending.get("requested"):
            await self._deps.feedback.clear(handler_input)
            return await PlaybackControls.restart_active(
                handler_input,
                speech=Speech.RATE_CONTENT_SAVED_RESUMING,
                deps=self._deps,
            )
        creator_id = selected_source.get("id")
        creator_name = selected_source.get("name")
        source_type = selected_source.get("kind") or "creator"
        User.update(handler_input, {"awaitingFollow": False, "pendingFollowSource": None})
        if DeferredIntentManager.has(handler_input):
            await self._deps.feedback.clear(handler_input)
            return await DeferredIntentManager.resume(handler_input)
        updated_store = User.snapshot(handler_input)
        if (
            creator_id
            and creator_name
            and (not Speech.is_bad_credit(creator_name))
            and (not FollowingManager.is_following(updated_store, creator_id, source_type))
        ):
            User.update(
                handler_input,
                {
                    "awaitingFollow": True,
                    "pendingFollowSource": {
                        "id": creator_id,
                        "name": creator_name,
                        "type": source_type,
                    },
                },
            )
            ask = Speech.FEEDBACK_FOLLOW_ASK(creator_name)
            return (
                handler_input.response_builder.speak(Ssml.ssml(ask))
                .reprompt(Ssml.ssml(Speech.FEEDBACK_FOLLOW_REPROMPT(creator_name)))
                .set_should_end_session(False)
                .response
            )
        await self._deps.feedback.clear(handler_input)
        title = (
            pending.get("title")
            or store.get("feedbackContentTitle")
            or store.get("currentContentTitle")
        )
        already_msg = (
            Speech.FEEDBACK_ENJOYED_ALREADY_FOLLOWING(title, creator_name)
            if title or creator_name
            else Speech.FEEDBACK_FOLLOW_DECLINED
        )
        return AlexaResponse.present_idle_next(handler_input, already_msg)


class SomewhatFeedback:
    def __init__(self, *, deps: object | None = None):
        self._deps = Feedback._dependencies(deps)

    async def execute(self, handler_input: HandlerInput):
        store = User.snapshot(handler_input)
        if not store.get("awaitingFeedback"):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        pending = dict(store.get("pendingFeedback") or {})
        await self._deps.feedback.submit(handler_input, "somewhat")
        selected_source = Feedback._feedback_source(pending, store)
        ListeningTracker.record(
            handler_input,
            category=pending.get("category") or store.get("feedbackCategory"),
            creator=selected_source.get("name"),
            liked=None,
        )
        await self._deps.feedback.clear(handler_input)
        if DeferredIntentManager.has(handler_input):
            return await DeferredIntentManager.resume(handler_input)
        return AlexaResponse.present_idle_next(handler_input, Speech.FEEDBACK_SOMEWHAT)


class NotEnjoyedFeedback:
    def __init__(self, *, deps: object | None = None):
        self._deps = Feedback._dependencies(deps)

    async def execute(self, handler_input: HandlerInput):
        store = User.snapshot(handler_input)
        if not store.get("awaitingFeedback"):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        pending = dict(store.get("pendingFeedback") or {})
        await self._deps.feedback.submit(handler_input, "not_enjoyed")
        selected_source = Feedback._feedback_source(pending, store)
        ListeningTracker.record(
            handler_input,
            category=pending.get("category") or store.get("feedbackCategory"),
            creator=selected_source.get("name"),
            liked=False,
        )
        report_context = Report.snapshot_report_context(store)
        FeedbackService.dismiss(handler_input)
        User.update(
            handler_input,
            {"awaitingReportDecision": True, "reportContext": report_context},
        )
        DialogStateManager.activate(
            handler_input,
            "report_decision",
            context=report_context,
            deferred_request=User.snapshot(handler_input).get("deferredIntent")
            if DeferredIntentManager.has(handler_input)
            else None,
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.FEEDBACK_NOT_ENJOYED))
            .reprompt(Ssml.ssml(Speech.FEEDBACK_REPORT_REPROMPT))
            .set_should_end_session(False)
            .response
        )


class SkipFeedback:
    def __init__(self, *, deps: object | None = None):
        self._deps = Feedback._dependencies(deps)

    async def execute(self, handler_input: HandlerInput):
        store = User.snapshot(handler_input)
        active_dialog = store.get("activeDialog")
        if (
            isinstance(active_dialog, dict)
            and active_dialog.get("type") == "ambiguity"
            or isinstance(store.get("pendingAmbiguity"), dict)
        ):
            DialogStateManager.dismiss_ambiguity(handler_input)
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml("No problem. What would you like to listen to?")
                )
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        if store.get("awaitingReportDecision"):
            await self._deps.feedback.clear(handler_input)
            if DeferredIntentManager.has(handler_input):
                return await DeferredIntentManager.resume(handler_input)
            return AlexaResponse.present_idle_next(handler_input, Speech.FEEDBACK_SKIP_INTRO)
        if not store.get("awaitingFeedback"):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        requested = bool((store.get("pendingFeedback") or {}).get("requested"))
        await self._deps.feedback.submit(handler_input, "skipped")
        await self._deps.feedback.clear(handler_input)
        if requested:
            return await PlaybackControls.restart_active(
                handler_input,
                speech=Speech.RATE_CONTENT_SKIPPED_RESUMING,
                deps=self._deps,
            )
        if DeferredIntentManager.has(handler_input):
            return await DeferredIntentManager.resume(handler_input)
        return AlexaResponse.present_idle_next(handler_input, Speech.FEEDBACK_SKIP_INTRO)


class Feedback:
    @staticmethod
    def _dependencies(deps: object | None):
        if deps is None:
            raise RuntimeError("Feedback requires injected dependencies")
        return deps

    @staticmethod
    def _feedback_source(pending: dict, store: dict) -> dict:
        return (
            ContentUtils.pick_content_source(
                {
                    "organizationId": pending.get("organizationId"),
                    "organizationName": pending.get("organizationName"),
                    "creatorId": pending.get("creatorId") or store.get("feedbackCreatorId"),
                    "creatorName": pending.get("creatorName") or store.get("feedbackCreator"),
                }
            )
            or {}
        )
