from __future__ import annotations

from src.alexa.context import RequestContext
from src.alexa.dialog import DeferredIntentManager, DialogStateManager
from src.alexa.feedback import AlexaFeedback
from src.alexa.feedback_service import FeedbackService
from src.alexa.playback_controls import PlaybackControls
from src.alexa.playback_speech import PlaybackSpeech
from src.alexa.playback_state import PlaybackQueue
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.feedback_contracts import FeedbackCommand
from src.models.report import Report
from src.models.social import FollowingManager, ListeningTracker
from src.models.user import User
from src.utils.content import ContentUtils


class RatingRequest:
    def __init__(
        self,
        feedback: FeedbackService,
        playback_controls: PlaybackControls,
        user: User,
    ) -> None:
        self._feedback = feedback
        self._playback_controls = playback_controls
        self._user = user

    async def execute(self, request: RequestContext):
        handler_input = request.handler_input
        pending = self._feedback.request_current_rating(handler_input)
        if pending:
            directive = await self._playback_controls.pause_active(handler_input)
            return AlexaFeedback.present_requested_feedback(
                handler_input,
                directive,
                pending,
                self._user.snapshot(handler_input),
            )
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.RATE_CONTENT_NOTHING))
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )


class FeedbackContinuation:
    @staticmethod
    def _context(subject: dict, store: dict) -> dict | None:
        queue = PlaybackQueue.read(store)
        if not queue:
            return None
        has_next = int(queue.get("currentIndex") or 0) < len(queue["orderedContentIds"]) - 1
        if not has_next and not PlaybackQueue.has_more_pages(queue):
            return None
        discovery = dict(
            subject.get("discoveryContext")
            or (store.get("activePlayback") or {}).get("discoveryContext")
            or queue.get("discoveryContext")
            or {}
        )
        name = str(discovery.get("name") or "").strip()
        kind = str(discovery.get("kind") or "").strip()
        if not name:
            if subject.get("publicationTitle"):
                kind, name = "publication", str(subject["publicationTitle"])
            elif subject.get("organizationName"):
                kind, name = "organization", str(subject["organizationName"])
            elif subject.get("creatorName"):
                kind, name = "creator", str(subject["creatorName"])
            elif subject.get("category"):
                kind, name = "topic", str(subject["category"])
        if not name:
            return None
        return {
            **discovery,
            "kind": kind or "topic",
            "name": name,
            "queueId": queue.get("queueId"),
            "currentIndex": int(queue.get("currentIndex") or 0),
        }

    @staticmethod
    def present(handler_input, subject: dict, store: dict, prefix: str, user: User):
        context = FeedbackContinuation._context(subject, store)
        if not context:
            return None
        user.update(
            handler_input,
            {
                "awaitingFeedbackContinuation": True,
                "feedbackContinuation": context,
                "_requiresReliableSave": True,
            },
        )
        DialogStateManager.activate(
            handler_input,
            "feedback_continuation",
            context=context,
        )
        question = AlexaFeedback.discovery_continuation_question(context)
        return (
            handler_input.response_builder.speak(Ssml.ssml(f"{prefix} {question}"))
            .reprompt(Ssml.ssml(AlexaFeedback.discovery_continuation_reprompt(context)))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    async def accept(
        handler_input, playback_controls: PlaybackControls, user: User
    ):
        context = dict(user.snapshot(handler_input).get("feedbackContinuation") or {})
        user.update(
            handler_input,
            {"awaitingFeedbackContinuation": False, "feedbackContinuation": None},
        )
        DialogStateManager.clear(handler_input, "feedback_continuation")
        return await playback_controls.play_queue_delta(
            handler_input,
            1,
            AlexaFeedback.discovery_continuing_speech(context),
        )

    @staticmethod
    def decline(handler_input, user: User):
        user.update(
            handler_input,
            {"awaitingFeedbackContinuation": False, "feedbackContinuation": None},
        )
        DialogStateManager.clear(handler_input, "feedback_continuation")
        return AlexaResponse.present_idle_next(handler_input, "Ok.")


class EnjoyedFeedback:
    def __init__(
        self,
        feedback: FeedbackService,
        playback_controls: PlaybackControls,
        user: User,
    ) -> None:
        self._feedback = feedback
        self._playback_controls = playback_controls
        self._user = user

    async def execute(self, request: RequestContext):
        handler_input = request.handler_input
        store = self._user.snapshot(handler_input)
        if not store.get("awaitingFeedback"):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        pending = dict(store.get("pendingFeedback") or {})
        await self._feedback.submit(
            request, FeedbackCommand("enjoyed")
        )
        selected_source = Feedback._feedback_source(pending, store)
        self._user.update(
            handler_input,
            {
                "listeningPattern": ListeningTracker.record(
                    store,
                    category=pending.get("category") or store.get("feedbackCategory"),
                    creator=selected_source.get("name"),
                    liked=True,
                )
            },
        )
        if pending.get("requested"):
            resume_speech = AlexaFeedback.resuming_speech(pending, store)
            await self._feedback.clear(handler_input)
            return await self._playback_controls.restart_active(
                handler_input,
                speech=resume_speech,
            )
        creator_id = selected_source.get("id")
        creator_name = selected_source.get("name")
        source_type = selected_source.get("kind") or "creator"
        self._user.update(handler_input, {"awaitingFollow": False, "pendingFollowSource": None})
        if DeferredIntentManager.has(handler_input):
            await self._feedback.clear(handler_input)
            return await DeferredIntentManager.resume(handler_input)
        await self._feedback.clear(handler_input)
        continuation = FeedbackContinuation.present(
            handler_input,
            pending,
            store,
            "Thanks for the feedback.",
            self._user,
        )
        if continuation:
            return continuation
        updated_store = self._user.snapshot(handler_input)
        if (
            creator_id
            and creator_name
            and (not Speech.is_bad_credit(creator_name))
            and (not FollowingManager.is_following(updated_store, creator_id, source_type))
        ):
            self._user.update(
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
    def __init__(
        self,
        feedback: FeedbackService,
        playback_controls: PlaybackControls,
        user: User,
    ) -> None:
        self._feedback = feedback
        self._playback_controls = playback_controls
        self._user = user

    async def execute(self, request: RequestContext):
        handler_input = request.handler_input
        store = self._user.snapshot(handler_input)
        if not store.get("awaitingFeedback"):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        pending = dict(store.get("pendingFeedback") or {})
        await self._feedback.submit(
            request, FeedbackCommand("somewhat")
        )
        selected_source = Feedback._feedback_source(pending, store)
        self._user.update(
            handler_input,
            {
                "listeningPattern": ListeningTracker.record(
                    store,
                    category=pending.get("category") or store.get("feedbackCategory"),
                    creator=selected_source.get("name"),
                    liked=None,
                )
            },
        )
        resume_speech = AlexaFeedback.resuming_speech(pending, store)
        await self._feedback.clear(handler_input)
        if pending.get("requested"):
            return await self._playback_controls.restart_active(
                handler_input,
                speech=resume_speech,
            )
        if DeferredIntentManager.has(handler_input):
            return await DeferredIntentManager.resume(handler_input)
        continuation = FeedbackContinuation.present(
            handler_input,
            pending,
            store,
            "Thanks for the feedback.",
            self._user,
        )
        if continuation:
            return continuation
        return AlexaResponse.present_idle_next(handler_input, Speech.FEEDBACK_SOMEWHAT)


class NotEnjoyedFeedback:
    def __init__(self, feedback: FeedbackService, user: User) -> None:
        self._feedback = feedback
        self._user = user

    async def execute(self, request: RequestContext):
        handler_input = request.handler_input
        store = self._user.snapshot(handler_input)
        if not store.get("awaitingFeedback"):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        pending = dict(store.get("pendingFeedback") or {})
        await self._feedback.submit(
            request, FeedbackCommand("not_enjoyed")
        )
        selected_source = Feedback._feedback_source(pending, store)
        self._user.update(
            handler_input,
            {
                "listeningPattern": ListeningTracker.record(
                    store,
                    category=pending.get("category") or store.get("feedbackCategory"),
                    creator=selected_source.get("name"),
                    liked=False,
                )
            },
        )
        report_context = Report.snapshot_report_context(store) or {}
        if pending.get("requested"):
            report_context["resumeAfterDecision"] = True
        FeedbackService.dismiss(handler_input)
        self._user.update(
            handler_input,
            {"awaitingReportDecision": True, "reportContext": report_context},
        )
        DialogStateManager.activate(
            handler_input,
            "report_decision",
            context=report_context,
            deferred_request=self._user.snapshot(handler_input).get("deferredIntent")
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
    def __init__(
        self,
        feedback: FeedbackService,
        playback_controls: PlaybackControls,
        user: User,
    ) -> None:
        self._feedback = feedback
        self._playback_controls = playback_controls
        self._user = user

    async def execute(self, request: RequestContext):
        handler_input = request.handler_input
        store = self._user.snapshot(handler_input)
        transport_skip = AlexaRequest.get_intent_name(handler_input) in {
            "AMAZON.NextIntent",
            "AMAZON.SkipIntent",
        }
        active_dialog = store.get("activeDialog")
        if (
            isinstance(active_dialog, dict)
            and active_dialog.get("type") == "ambiguity"
            or isinstance(store.get("pendingAmbiguity"), dict)
        ):
            DialogStateManager.dismiss_ambiguity(handler_input)
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(Speech.CHOICES_DISMISSED)
                )
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        if store.get("awaitingFeedbackContinuation") and transport_skip:
            self._user.update(
                handler_input,
                {"awaitingFeedbackContinuation": False, "feedbackContinuation": None},
            )
            DialogStateManager.clear(handler_input, "feedback_continuation")
            return await self._playback_controls.play_queue_delta(
                handler_input,
                1,
                PlaybackSpeech.PLAYING_NEXT,
            )
        if store.get("awaitingReportDecision"):
            resume_after_decision = bool(
                (store.get("reportContext") or {}).get("resumeAfterDecision")
            )
            resume_speech = AlexaFeedback.resuming_speech(
                store.get("reportContext"),
                store,
                skipped=True,
            )
            await self._feedback.clear(handler_input)
            if resume_after_decision:
                return await self._playback_controls.restart_active(
                    handler_input,
                    speech=resume_speech,
                )
            if DeferredIntentManager.has(handler_input):
                return await DeferredIntentManager.resume(handler_input)
            continuation = FeedbackContinuation.present(
                handler_input,
                dict(store.get("reportContext") or {}),
                store,
                "Ok.",
                self._user,
            )
            if continuation:
                return continuation
            return AlexaResponse.present_idle_next(handler_input, Speech.FEEDBACK_SKIP_INTRO)
        if not store.get("awaitingFeedback"):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        pending = store.get("pendingFeedback") or {}
        requested = bool(pending.get("requested"))
        resume_speech = AlexaFeedback.resuming_speech(pending, store, skipped=True)
        await self._feedback.submit(
            request, FeedbackCommand("skipped")
        )
        await self._feedback.clear(handler_input)
        if requested:
            return await self._playback_controls.restart_active(
                handler_input,
                speech=resume_speech,
            )
        if DeferredIntentManager.has(handler_input):
            return await DeferredIntentManager.resume(handler_input)
        if transport_skip:
            return await self._playback_controls.play_queue_delta(
                handler_input,
                1,
                PlaybackSpeech.PLAYING_NEXT,
            )
        continuation = FeedbackContinuation.present(
            handler_input,
            dict(pending),
            store,
            "Ok.",
            self._user,
        )
        if continuation:
            return continuation
        return AlexaResponse.present_idle_next(handler_input, Speech.FEEDBACK_SKIP_INTRO)


class Feedback:
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
