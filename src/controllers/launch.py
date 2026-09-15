from __future__ import annotations

from src.services.logging_control import ApplicationLog

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.constants.onboarding import OnboardingConstants
from src.models.dialog import DialogStateManager
from src.models.launch_workflow import LaunchWorkflow
from src.models.onboarding import TownCapture
from src.models.playback import Playback
from src.models.user import User


class LaunchRequestHandler(AbstractRequestHandler):

    def __init__(self, workflow: LaunchWorkflow, playback: Playback) -> None:
        self._workflow = workflow
        self._playback = playback

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "LaunchRequest"

    async def handle(self, handler_input: HandlerInput):
        if not AlexaRequest.get_user_id(handler_input):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.ERROR_GENERIC))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        try:
            await self._playback.flush_previous(
                AlexaRequest.get_user_id(handler_input), None, handler_input
            )
        except Exception as err:
            ApplicationLog.warning("Hear: launch flush failed error=%s", type(err).__name__)
        try:
            return await self._workflow.execute(handler_input)
        except Exception as err:
            ApplicationLog.error("Hear: launch failed %s", err)
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.WELCOME_ERROR))
                .reprompt(Ssml.ssml(Speech.REPROMPT_NO_CITY))
                .set_should_end_session(False)
                .response
            )


class TownCaptureHandler(AbstractRequestHandler):
    def __init__(self, action: TownCapture, user: User) -> None:
        self._action = action
        self._user = user

    def can_handle(self, handler_input: HandlerInput) -> bool:
        if AlexaRequest.get_request_type(handler_input) != "IntentRequest":
            return False
        store = self._user.snapshot(handler_input)
        if store.get("onboardingStage") != OnboardingConstants.ONBOARDING_ASK_TOWN:
            return False
        active_dialog = DialogStateManager.get_active(handler_input)
        if active_dialog and active_dialog.get("type") != "onboarding":
            return False
        nlp = (RequestContext.request(handler_input) or {}).get("_nlp", {})
        nlp_intent = nlp.get("intent")
        if nlp_intent == "town_capture":
            return True
        if nlp_intent:
            return self._is_residual_location(handler_input, nlp)
        return AlexaRequest.get_intent_name(handler_input) in {
            "TownCaptureIntent",
            "SetLocationIntent",
            "SearchLocationIntent",
            "AMAZON.NoIntent",
            "SkipFeedbackIntent",
            "AMAZON.NextIntent",
            "AMAZON.SkipIntent",
            "AMAZON.CancelIntent",
        }

    @staticmethod
    def _is_residual_location(handler_input: HandlerInput, nlp: dict) -> bool:
        return bool(
            nlp.get("intent") == "search"
            and not (nlp.get("entities") or [])
            and (nlp.get("slots") or {}).get("residualQuery")
            and AlexaRequest.get_intent_name(handler_input)
            in {"TownCaptureIntent", "SetLocationIntent"}
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._action.execute(handler_input)
