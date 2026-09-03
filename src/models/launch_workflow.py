from __future__ import annotations

import logging
import time

from ask_sdk_core.handler_input import HandlerInput

from src.alexa.feedback import AlexaFeedback
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.dialog import DialogStateManager
from src.models.onboarding import LaunchTracker, Onboarding
from src.utils.deadline import DeadlineBudget


class LaunchWorkflow:
    logger = logging.getLogger(__name__)
    PROFILE_TTL_MS = 24 * 60 * 60 * 1000

    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    async def execute(self, handler_input: HandlerInput):
        store = self._initial_store(handler_input)
        user_name = self._user_name(store)
        protected_response = self._protected_response(handler_input, store, user_name)
        if protected_response is not None:
            return protected_response
        try:
            store = await self._ensure_listener_data_for_launch(handler_input, store)
        except Exception:
            pass
        store = await self._sync_listener_for_launch(handler_input, store)
        notification_response = await self._deps.notifications.offer(handler_input)
        if notification_response is not None:
            return notification_response
        store = self._deps.user.snapshot(handler_input)
        pending_response = await self._pending_response(
            handler_input,
            store,
            self._user_name(store),
        )
        if pending_response is not None:
            return pending_response
        self._schedule_launch_background_work(handler_input, store)
        return self._welcome_response(handler_input, store)

    def _initial_store(self, handler_input: HandlerInput) -> dict:
        store = self._deps.user.snapshot(handler_input)
        DialogStateManager.clear_transient_discovery(handler_input)
        store = self._deps.user.snapshot(handler_input)
        launch = LaunchTracker.record(AlexaRequest.get_user_id(handler_input), store)
        if launch.get("save"):
            self._deps.user.update(handler_input, launch["save"])
            return self._deps.user.snapshot(handler_input)
        return store

    def _protected_response(
        self, handler_input: HandlerInput, store: dict, user_name: str | None
    ):
        if store.get("onboardingStage") == "confirm_town_for_community":
            return Onboarding.start_town_capture(handler_input, store, user_name, deps=self._deps)
        if store.get("awaitingContinueAfterFlag"):
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
        if self._deps.playback.state.has_unfinished(store):
            return self._unfinished_response(handler_input, store)
        if store.get("awaitingFeedback") and store.get("pendingFeedback"):
            return AlexaFeedback.present_pending_feedback(handler_input, store)
        if store.get("awaitingFeedback") and (
            store.get("feedbackContentTitle") or store.get("feedbackPromptText")
        ):
            return await self._feedback_response(handler_input, store, user_name)
        return None

    def _unfinished_response(self, handler_input: HandlerInput, store: dict):
        active = self._deps.playback.state.from_store(store) or {}
        title = Speech.escape_ssml_lite(AlexaFeedback.subject_title(active, store))
        self._deps.user.update(handler_input, {"awaitingResume": True})
        DialogStateManager.activate(handler_input, "resume", context=active)
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(f"You did not finish {title}. Would you like to continue?")
            )
            .reprompt(Ssml.ssml(f"Would you like to continue {title}?"))
            .set_should_end_session(False)
            .response
        )

    async def _feedback_response(
        self, handler_input: HandlerInput, store: dict, user_name: str | None
    ):
        await self._deps.reminders.cancel(handler_input)
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
        user_name = self._user_name(store)
        locality = store.get("locality")
        city = store.get("userCity") or locality
        is_first_time = store.get("playCount", 0) == 0 and not store.get("lastToken")
        if is_first_time and city:
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(Speech.WELCOME_FIRST_HAS_CITY(user_name, city))
                )
                .set_should_end_session(False)
                .response
            )
        if is_first_time:
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.WELCOME_FIRST(user_name)))
                .set_should_end_session(False)
                .response
            )
        return Onboarding.handle_returning_user(handler_input, store, user_name, locality)

    @staticmethod
    def _user_name(store: dict) -> str | None:
        return store.get("userName") or store.get("givenName") or store.get("fullName")

    @classmethod
    def _listener_data_is_cached(cls, store: dict) -> bool:
        if not store:
            return False
        resolved_at = store.get("listenerProfileResolvedAt", 0)
        has_name = bool(store.get("userName") or store.get("fullName") or store.get("givenName"))
        if not has_name and not store.get("userEmail"):
            return False
        return bool(resolved_at and int(time.time() * 1000) - resolved_at < cls.PROFILE_TTL_MS)

    async def _ensure_listener_data_for_launch(
        self, handler_input: HandlerInput, store: dict
    ) -> dict:
        remaining = DeadlineBudget.get_lambda_remaining_ms(handler_input)
        if isinstance(remaining, (int, float)) and remaining < 3500:
            self.logger.info("Hear: launch enrichment skipped (budget) remainingMs=%s", remaining)
            return store
        try:
            if not self._listener_data_is_cached(store):
                enriched = await self._deps.listener_profile.apply_listener_profile(handler_input)
                self.logger.info("Hear: launch enrichment done")
                return enriched
        except Exception as err:
            self.logger.warning("Hear: launch enrichment failed %s", err)
        return store

    async def _sync_listener_for_launch(self, handler_input: HandlerInput, store: dict) -> dict:
        try:
            await self._deps.listener_sync.sync_for_launch(handler_input)
            return self._deps.user.snapshot(handler_input)
        except Exception as err:
            self.logger.warning("Hear: listener launch sync failed error=%s", type(err).__name__)
            return store

    @staticmethod
    def _schedule_launch_background_work(handler_input: HandlerInput, store: dict) -> None:
        del handler_input, store
