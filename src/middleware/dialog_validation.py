from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import (
    AbstractRequestHandler,
    AbstractRequestInterceptor,
)

from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.search_speech import SearchSpeech
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.constants.dialog import DialogConstants
from src.models.dialog import DialogStateManager


class DialogValidationPolicy:
    logger = logging.getLogger(__name__)
    _EXIT_INTENTS = {"AMAZON.CancelIntent", "AMAZON.StopIntent"}
    _BINARY_INTENTS = _EXIT_INTENTS | {"AMAZON.YesIntent", "AMAZON.NoIntent"}
    _AMBIGUITY_INTENTS = _EXIT_INTENTS | {
        "ClarifySelectionIntent",
        "ShowMoreBrowseIntent",
        "SkipFeedbackIntent",
        "AMAZON.NoIntent",
    }
    _FEEDBACK_INTENTS = _EXIT_INTENTS | {
        "FeedbackEnjoyedIntent",
        "FeedbackSomewhatIntent",
        "FeedbackNotEnjoyedIntent",
        "SkipFeedbackIntent",
        "AMAZON.YesIntent",
        "AMAZON.NoIntent",
        "AMAZON.RepeatIntent",
        "AMAZON.StartOverIntent",
        "ReportCreatorIntent",
        "ReportContentIntent",
        "AMAZON.NextIntent",
        "AMAZON.SkipIntent",
        "AMAZON.PreviousIntent",
        "AMAZON.PauseIntent",
        "AMAZON.ResumeIntent",
    }
    _TRANSPORT_REQUEST_TYPES = {
        "PlaybackController.NextCommandIssued",
        "PlaybackController.PreviousCommandIssued",
        "PlaybackController.PauseCommandIssued",
        "PlaybackController.PlayCommandIssued",
    }
    _BINARY_DIALOGS = {"search_confirmation", "resume", "latest_source"}
    _LOCATION_ONBOARDING_INTENTS = _BINARY_INTENTS | {
        "TownCaptureIntent",
        "SetLocationIntent",
        "SkipFeedbackIntent",
    }
    _REPORT_DECISION_INTENTS = _EXIT_INTENTS | {
        "ReportCreatorIntent",
        "ReportContentIntent",
        "SkipFeedbackIntent",
        "AMAZON.YesIntent",
        "AMAZON.NoIntent",
    }

    @staticmethod
    def _ambiguity_prompt(active: dict) -> tuple[str, str]:
        context = active.get("context") or {}
        candidates = list(
            context.get("displayedCandidates")
            or context.get("choiceCandidates")
            or context.get("candidates")
            or []
        )[:3]
        message = SearchSpeech.ambiguous_reference_message("that name", candidates)
        ordinal = " You can say the first one, the second one, or show more."
        return (
            message + ordinal,
            "Say a name, the first one, the second one, or show more.",
        )

    @staticmethod
    def _binary_prompt(active: dict) -> tuple[str, str]:
        context = active.get("context") or {}
        original = str(
            context.get("question")
            or context.get("prompt")
            or context.get("confirmText")
            or context.get("confirmationLabel")
            or ""
        ).strip()
        if active.get("type") == "search_confirmation" and original:
            speech = f"Did you want me to play {Speech.escape_ssml_lite(original)}? Please say yes or no."
        elif active.get("type") == "resume":
            speech = "Would you like to continue that recording? Please say yes or no."
        elif original:
            speech = f"{Speech.escape_ssml_lite(original)} Please say yes or no."
        else:
            speech = "I need a yes or no answer before we continue. Please say yes or no."
        return (speech, "Please say yes or no.")

    @staticmethod
    def _onboarding_binary_prompt(stage: str) -> tuple[str, str]:
        if stage == "ask_permission":
            speech = "Would you like me to use your device location? Please say yes or no."
        else:
            speech = "Is that the correct city? Please say yes or no."
        return (speech, "Please say yes or no.")

    @staticmethod
    def dialog_validation_failure(handler_input) -> dict | None:
        if AlexaRequest.get_request_type(handler_input) != "IntentRequest":
            return None
        active = DialogStateManager.get_active(handler_input)
        if not active:
            return None
        intent_name = AlexaRequest.get_intent_name(handler_input)
        dialog_type = active.get("type")
        context = active.get("context") or {}
        onboarding_stage = str(context.get("stage") or "")
        if (
            dialog_type == "onboarding"
            and onboarding_stage in {"ask_permission", "await_location_confirm"}
            and (
                intent_name
                not in (
                    DialogValidationPolicy._LOCATION_ONBOARDING_INTENTS
                    if onboarding_stage == "ask_permission"
                    else DialogValidationPolicy._BINARY_INTENTS
                )
            )
        ):
            speech, reprompt = DialogValidationPolicy._onboarding_binary_prompt(onboarding_stage)
        elif (
            dialog_type == "ambiguity"
            and intent_name not in DialogValidationPolicy._AMBIGUITY_INTENTS
        ):
            speech, reprompt = DialogValidationPolicy._ambiguity_prompt(active)
        elif (
            dialog_type in DialogValidationPolicy._BINARY_DIALOGS
            and intent_name not in DialogValidationPolicy._BINARY_INTENTS
        ):
            speech, reprompt = DialogValidationPolicy._binary_prompt(active)
        elif (
            dialog_type == "report_decision"
            and intent_name not in DialogValidationPolicy._REPORT_DECISION_INTENTS
        ):
            speech = "Would you like to report that recording? Say report, skip, yes, or no."
            reprompt = "Say report, skip, yes, or no."
        elif (
            dialog_type == "feedback"
            and intent_name not in DialogValidationPolicy._FEEDBACK_INTENTS
        ):
            speech = (
                "Please answer the feedback question first. " + Speech.FEEDBACK_AWAITING_REPROMPT
            )
            reprompt = Speech.FEEDBACK_AWAITING_REPROMPT
        else:
            return None
        return {"dialogType": dialog_type, "speech": speech, "reprompt": reprompt}


class DialogValidationInterceptor(AbstractRequestInterceptor):
    def process(self, handler_input) -> None:
        if (
            AlexaRequest.get_request_type(handler_input)
            in DialogValidationPolicy._TRANSPORT_REQUEST_TYPES
        ):
            return
        failure = DialogValidationPolicy.dialog_validation_failure(handler_input)
        if not failure:
            return
        attrs = RequestContext.request(handler_input)
        attrs[DialogConstants.VALIDATION_FAILURE] = failure
        RequestContext.replace_request(handler_input, attrs)
        DialogValidationPolicy.logger.info(
            "Hear: dialog input rejected dialog=%s intent=%s",
            failure["dialogType"],
            AlexaRequest.get_intent_name(handler_input),
        )


class DialogValidationGateHandler(AbstractRequestHandler):
    def can_handle(self, handler_input) -> bool:
        return bool(RequestContext.request(handler_input).get(DialogConstants.VALIDATION_FAILURE))

    def handle(self, handler_input):
        failure = RequestContext.request(handler_input)[DialogConstants.VALIDATION_FAILURE]
        return (
            handler_input.response_builder.speak(Ssml.ssml(failure["speech"]))
            .reprompt(Ssml.ssml(failure["reprompt"]))
            .set_should_end_session(False)
            .response
        )
