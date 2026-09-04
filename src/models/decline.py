from __future__ import annotations

from ask_sdk_core.handler_input import HandlerInput

from src.alexa.context import RequestContext
from src.alexa.playback import AlexaPlayback
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.dialog import DialogStateManager
from src.models.feedback import FeedbackService
from src.models.feedback_response import NotEnjoyedFeedback, SkipFeedback
from src.models.playback import Playback


class Decline:
    """State-machine based No handler.

    Routes No based on state:
    1. awaitingSearchConfirmation  -> cycle to next suggestion or give up
    2. listModeActive              -> advance list position
    4. awaitingStillListening      -> stop and goodbye
    5. awaitingContinueAfterFlag   -> skip to next
    6. awaitingFeedback            -> delegate to FeedbackNotEnjoyed
    7. awaitingFollow              -> clear feedback
    9. awaitingReportDecision      -> delegate to SkipFeedback
    10. pendingNlpSuggestion       -> reject NLP suggestion
    Fallback                       -> generic welcome reprompt
    """

    def __init__(self, *, deps: object | None = None):
        if deps is None:
            raise RuntimeError("Confirmation requires injected dependencies")
        self._deps = deps

    @staticmethod
    def _generic_response(handler_input):
        return (
            handler_input.response_builder.speak(Speech.WELCOME_REPROMPT)
            .reprompt(Speech.WELCOME_REPROMPT)
            .set_should_end_session(False)
            .response
        )

    async def _setup_dialog_response(
        self,
        handler_input,
        store: dict,
        session: dict,
        dialog_type: str | None,
    ):
        if dialog_type == "ambiguity":
            DialogStateManager.dismiss_ambiguity(handler_input)
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(Speech.CHOICES_DISMISSED)
                )
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        if dialog_type == "asr_repair":
            DialogStateManager.clear(handler_input, "asr_repair")
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml("No problem. What would you like to listen to?")
                )
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        if dialog_type == "latest_source":
            self._deps.user.update(handler_input, {"pendingLatestSource": None})
            DialogStateManager.clear(handler_input, "latest_source")
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.LATEST_SOURCE_DECLINED))
                .reprompt(Ssml.ssml(Speech.LATEST_SOURCE_DECLINED))
                .set_should_end_session(False)
                .response
            )
        if dialog_type == "notification":
            return await self._deps.notifications.decline(handler_input)
        search_pending = bool(
            dialog_type == "search_confirmation"
            or not dialog_type
            and (
                store.get("awaitingSearchConfirmation") or session.get("awaitingSearchConfirmation")
            )
        )
        if search_pending:
            return self._handle_search_no(handler_input, store, session)
        if store.get("awaitingLocationConfirm"):
            self._deps.onboarding.clear_invalid_confirmation(handler_input)
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.LOCATION_RETRY))
                .reprompt(Ssml.ssml("Which city should I set?"))
                .set_should_end_session(False)
                .response
            )
        if store.get("awaitingCommunityPlayback"):
            self._deps.user.update(handler_input, {"awaitingCommunityPlayback": False})
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml("No problem. What would you like to listen to?")
                )
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        return None

    async def _activity_dialog_response(
        self,
        handler_input,
        store: dict,
        dialog_type: str | None,
    ):
        if (
            dialog_type == "report_decision"
            or not dialog_type
            and store.get("awaitingReportDecision")
        ):
            return await SkipFeedback(deps=self._deps).execute(handler_input)
        if dialog_type == "feedback" or not dialog_type and store.get("awaitingFeedback"):
            return await NotEnjoyedFeedback(deps=self._deps).execute(handler_input)
        if dialog_type == "resume" or not dialog_type and store.get("awaitingResume"):
            return self._handle_resume_no(handler_input, store)
        return None

    async def _state_response(self, handler_input, store: dict):
        if store.get("onboardingStage") == "confirm_town_for_community":
            self._deps.user.update(
                handler_input,
                {"onboardingStage": None, "awaitingCommunityPlayback": False},
            )
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.COMMUNITY_LOCATION_DECLINED,
                Speech.WELCOME_REPROMPT,
            )
        if store.get("awaitingProfilePermission"):
            self._deps.user.update(
                handler_input,
                {"awaitingProfilePermission": False, "listenerType": "guest"},
            )
            try:
                await self._deps.listener_sync.sync_for_launch(handler_input)
            except Exception:
                pass
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(Speech.PROFILE_PERMISSION_SKIPPED)
                )
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        if store.get("listModeActive"):
            return self._handle_list_mode_no(handler_input, store)
        if store.get("awaitingStillListening"):
            return self._handle_still_listening_no(handler_input)
        if store.get("awaitingNotificationChoice"):
            return await self._deps.notifications.decline(handler_input)
        if store.get("awaitingContinueAfterFlag"):
            self._deps.user.update(handler_input, {"awaitingContinueAfterFlag": False})
            return await Playback.play_queue_delta(
                handler_input, 1, "Playing the next recording.", deps=self._deps
            )
        if store.get("awaitingFeedback"):
            return await NotEnjoyedFeedback(deps=self._deps).execute(handler_input)
        if store.get("awaitingFollow"):
            await self._deps.feedback.clear(handler_input)
            return AlexaResponse.present_idle_next(handler_input, Speech.FEEDBACK_FOLLOW_DECLINED)
        if store.get("awaitingReportDecision"):
            return await SkipFeedback(deps=self._deps).execute(handler_input)
        if store.get("pendingNlpSuggestion"):
            return self._reject_nlp_suggestion(handler_input, store)
        return None

    async def execute(self, handler_input: HandlerInput):
        store = self._deps.user.snapshot(handler_input)
        session = RequestContext.session(handler_input) or {}
        dialog_type = (DialogStateManager.get_active(handler_input) or {}).get("type")
        response = await self._setup_dialog_response(handler_input, store, session, dialog_type)
        response = response or await self._activity_dialog_response(
            handler_input, store, dialog_type
        )
        response = response or await self._state_response(handler_input, store)
        return response or Decline._generic_response(handler_input)

    def _handle_search_no(self, handler_input, store, session_attrs):
        """Cycle through search suggestions or give up."""
        if store.get("pendingResolution") or session_attrs.get("pendingResolution"):
            self._deps.user.update(
                handler_input,
                {
                    "awaitingSearchConfirmation": False,
                    "pendingResolution": None,
                    "pendingAmbiguity": None,
                    "awaitingLocationConfirm": False,
                    "pendingLocationConfirm": None,
                    "_requiresReliableSave": True,
                },
            )
            DialogStateManager.clear(handler_input, "search_confirmation")
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(
                        "No problem. You can ask for news or sport, play from a talking newspaper, or say what's trending. What would you like to listen to?"
                    )
                )
                .reprompt(
                    Ssml.ssml(
                        "You can ask for news or sport, a talking newspaper, or what's trending."
                    )
                )
                .set_should_end_session(False)
                .response
            )
        if store.get("pendingOrganizationConfirmation"):
            self._deps.user.update(
                handler_input,
                {
                    "awaitingSearchConfirmation": False,
                    "pendingOrganizationConfirmation": False,
                    "pendingSearchIntent": None,
                    "pendingSearchQuery": None,
                    "pendingSearchSlots": {},
                    "pendingSuggestions": [],
                    "suggestionIndex": 0,
                    "awaitingOrganizationName": True,
                },
            )
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml("Okay. Which talking newspaper did you mean?")
                )
                .reprompt(Ssml.ssml(Speech.ASK_TALKING_NEWSPAPER_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        attrs = RequestContext.request(handler_input)
        attrs.pop("_pendingConfirmation", None)
        RequestContext.replace_request(handler_input, attrs)
        suggestions = (
            session_attrs.get("pendingSuggestions")
            if session_attrs.get("pendingSuggestions")
            else store.get("pendingSuggestions", [])
        )
        idx = (session_attrs.get("suggestionIndex") or store.get("suggestionIndex") or 0) + 1
        if idx < len(suggestions):
            next_sug = suggestions[idx]
            RequestContext.replace_session(
                handler_input,
                {
                    "awaitingSearchConfirmation": True,
                    "pendingSearchIntent": session_attrs.get("pendingSearchIntent"),
                    "pendingSearchQuery": session_attrs.get("pendingSearchQuery"),
                    "pendingSuggestions": suggestions,
                    "suggestionIndex": idx,
                },
            )
            next_name = next_sug.get("display") or next_sug.get("query") or next_sug.get("intent")
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(f"Maybe {Speech.escape_ssml_lite(str(next_name))}?")
                )
                .set_should_end_session(False)
                .response
            )
        self._deps.user.update(
            handler_input,
            {
                "awaitingSearchConfirmation": False,
                "pendingSearchIntent": None,
                "pendingSearchQuery": None,
                "pendingSearchSlots": {},
                "pendingSuggestions": [],
                "suggestionIndex": 0,
                "excludedSuggestions": [],
            },
        )
        return (
            handler_input.response_builder.speak(
                Ssml.ssml("No problem. What would you like to listen to instead?")
            )
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    def _handle_list_mode_no(self, handler_input, store):
        """Decline the offered queue item without creating another queue."""
        del store
        self._deps.user.update(handler_input, {"listModeActive": False})
        return (
            handler_input.response_builder.speak(
                Ssml.ssml("No problem. What would you like to listen to?")
            )
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    def _handle_resume_no(self, handler_input, store):
        state = self._deps.playback.state.current(handler_input)
        if state:
            state = self._deps.playback.state.merge(handler_input, {"status": "abandoned"})
            FeedbackService.update_publication_progress(handler_input, state)
            if FeedbackService.finalize_publication(handler_input, state.get("publicationId")):
                FeedbackService.activate_best(handler_input)
        self._deps.user.update(handler_input, {"awaitingResume": False})
        DialogStateManager.clear(handler_input, "resume")
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.RESUME_DECLINED_NEXT_OPTIONS))
            .reprompt(Ssml.ssml(Speech.RESUME_DECLINED_NEXT_OPTIONS_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    def _handle_still_listening_no(self, handler_input):
        """Stop after still-listening prompt declined."""
        self._deps.user.update(
            handler_input,
            {"awaitingStillListening": False, "awaitingContinueAfterFlag": False},
        )
        self._deps.playback.queue.clear(handler_input)
        return (
            handler_input.response_builder.speak(Speech.GOODBYE)
            .add_directive(AlexaPlayback.build_stop_directive())
            .response
        )

    def _reject_nlp_suggestion(self, handler_input, store):
        """Reject the current NLP suggestion; offer the next if available."""
        suggestions = store.get("pendingNlpSuggestion") or []
        if len(suggestions) > 1:
            remaining = suggestions[1:]
            self._deps.user.update(handler_input, {"pendingNlpSuggestion": remaining})
            next_sug = remaining[0]
            display_text = (
                next_sug.get("displayText")
                or f"{next_sug.get('intent')} {next_sug.get('query', '')}".strip()
            )
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(
                        f"How about {Speech.escape_ssml_lite(display_text)}? Say yes to try that."
                    )
                )
                .reprompt(Ssml.ssml("Say yes to confirm, or no for other options."))
                .set_should_end_session(False)
                .response
            )
        self._deps.user.update(handler_input, {"pendingNlpSuggestion": None})
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(
                    "No problem. You can say what's trending, play followed by a topic, or play from a creator."
                )
            )
            .reprompt(Ssml.ssml("Try saying what's trending, or play news."))
            .set_should_end_session(False)
            .response
        )
