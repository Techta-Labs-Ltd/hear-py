"""Alexa adapter for launch orchestration around the pure launch policy."""

from __future__ import annotations

import time

from ask_sdk_core.handler_input import HandlerInput

from src.alexa.dialog import DialogStateManager
from src.alexa.feedback import AlexaFeedback
from src.alexa.onboarding import LaunchTracker, Onboarding
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.resume_speech import ResumeSpeech
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.launch_policy import LaunchPolicy
from src.services.logging_control import ApplicationLog
from src.utils.deadline import DeadlineBudget


class LaunchWorkflow:
    PROFILE_TTL_MS = 24 * 60 * 60 * 1000

    def __init__(
        self,
        *,
        user,
        notifications,
        playback,
        listener_profile,
        listener_sync,
        start_town_capture,
    ) -> None:
        self._user = user
        self._notifications = notifications
        self._playback = playback
        self._listener_profile = listener_profile
        self._listener_sync = listener_sync
        self._start_town_capture = start_town_capture

    async def execute(self, handler_input: HandlerInput):
        store = self._initial_store(handler_input)
        user_name = LaunchPolicy.user_name(store)
        protected_response = self._protected_response(handler_input, store, user_name)
        if protected_response is not None:
            return protected_response
        try:
            store = await self._ensure_listener_data_for_launch(handler_input, store)
        except Exception:
            pass
        store = await self._sync_listener_for_launch(handler_input, store)
        notification_response = await self._notifications.offer(handler_input)
        if notification_response is not None:
            return notification_response
        store = self._user.snapshot(handler_input)
        pending_response = await self._pending_response(
            handler_input,
            store,
            LaunchPolicy.user_name(store),
        )
        if pending_response is not None:
            return pending_response
        self._schedule_launch_background_work(handler_input, store)
        return self._welcome_response(handler_input, store)

    def _initial_store(self, handler_input: HandlerInput) -> dict:
        store = self._user.snapshot(handler_input)
        DialogStateManager.clear_transient_discovery(handler_input)
        store = self._user.snapshot(handler_input)
        launch = LaunchTracker.record(AlexaRequest.get_user_id(handler_input) or "", store)
        if launch.get("save"):
            self._user.update(handler_input, launch["save"])
            return self._user.snapshot(handler_input)
        return store

    def _protected_response(
        self, handler_input: HandlerInput, store: dict, user_name: str | None
    ):
        decision = LaunchPolicy.protected(store)
        if decision.kind == "town_capture":
            return self._start_town_capture(handler_input, store, user_name)
        if decision.kind == "continue_after_flag":
            subject = store.get("activePlayback") or store.get("reportContext") or {}
            question = AlexaFeedback.keep_listening_question(subject, store)
            reprompt = AlexaFeedback.keep_listening_reprompt(subject, store)
            return (
                handler_input.response_builder.speak(Ssml.ssml(question))
                .reprompt(Ssml.ssml(reprompt))
                .set_should_end_session(False)
                .response
            )
        return None

    async def _pending_response(
        self, handler_input: HandlerInput, store: dict, user_name: str | None
    ):
        decision = LaunchPolicy.pending(
            store, has_unfinished_playback=self._playback.state.has_unfinished(store)
        )
        if decision.kind == "unfinished_playback":
            return self._unfinished_response(handler_input, store)
        if decision.kind == "pending_feedback":
            return AlexaFeedback.present_pending_feedback(handler_input, store)
        if decision.kind == "ask_pending_feedback":
            return await self._feedback_response(handler_input, store, user_name)
        return None

    def _unfinished_response(self, handler_input: HandlerInput, store: dict):
        active = self._playback.state.from_store(store) or {}
        self._user.update(handler_input, {"awaitingResume": True})
        DialogStateManager.activate(handler_input, "resume", context=active)
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(ResumeSpeech.prompt(active, store))
            )
            .reprompt(Ssml.ssml(ResumeSpeech.reprompt(active, store)))
            .set_should_end_session(False)
            .response
        )

    async def _feedback_response(
        self, handler_input: HandlerInput, store: dict, user_name: str | None
    ):
        title = Speech.humanize_spoken_title(store.get("feedbackContentTitle")) or "that track"
        creator = Speech.escape_ssml_lite(store.get("feedbackCreator") or "the creator")
        prompt = Speech.LAUNCH_PENDING_FEEDBACK(title, creator, user_name)
        return (
            handler_input.response_builder.speak(Ssml.ssml(prompt))
            .reprompt(Ssml.ssml(Speech.FEEDBACK_AWAITING_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    def _welcome_response(self, handler_input: HandlerInput, store: dict):
        decision = LaunchPolicy.welcome(store)
        if decision.kind == "first_with_city":
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.WELCOME_FIRST_HAS_CITY(decision.user_name, decision.city),
            )
        if decision.kind == "first_without_city":
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.WELCOME_FIRST(decision.user_name),
            )
        return Onboarding.handle_returning_user(
            handler_input, store, decision.user_name, decision.locality
        )

    @classmethod
    def _listener_data_is_cached(cls, store: dict) -> bool:
        if not store:
            return False
        resolved_at = store.get("listenerProfileResolvedAt", 0)
        has_name = bool(store.get("userName") or store.get("fullName"))
        if not has_name and not store.get("userEmail"):
            return False
        return bool(resolved_at and int(time.time() * 1000) - resolved_at < cls.PROFILE_TTL_MS)

    async def _ensure_listener_data_for_launch(
        self, handler_input: HandlerInput, store: dict
    ) -> dict:
        remaining = DeadlineBudget.get_lambda_remaining_ms(handler_input)
        if isinstance(remaining, (int, float)) and remaining < 3500:
            ApplicationLog.info("Hear: launch enrichment skipped (budget) remainingMs=%s", remaining)
            return store
        try:
            if not self._listener_data_is_cached(store):
                enriched = await self._listener_profile.apply_listener_profile(handler_input)
                ApplicationLog.info("Hear: launch enrichment done")
                return enriched
        except Exception as err:
            ApplicationLog.warning("Hear: launch enrichment failed error=%s", type(err).__name__)
        return store

    async def _sync_listener_for_launch(self, handler_input: HandlerInput, store: dict) -> dict:
        try:
            await self._listener_sync.sync_for_launch(handler_input)
            return self._user.snapshot(handler_input)
        except Exception as err:
            ApplicationLog.warning("Hear: listener launch sync failed error=%s", type(err).__name__)
            return store

    @staticmethod
    def _schedule_launch_background_work(handler_input: HandlerInput, store: dict) -> None:
        del handler_input, store
