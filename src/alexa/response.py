from __future__ import annotations

from copy import deepcopy

from src.alexa.speech import Speech
from src.alexa.ssml import Ssml


class AlexaResponse:
    CALLBACK_DIRECTIVES = {
        "AudioPlayer.PlaybackStarted": frozenset({"AudioPlayer.Stop", "AudioPlayer.ClearQueue"}),
        "AudioPlayer.PlaybackFinished": frozenset({"AudioPlayer.Stop", "AudioPlayer.ClearQueue"}),
        "AudioPlayer.PlaybackNearlyFinished": frozenset(
            {"AudioPlayer.Play", "AudioPlayer.Stop", "AudioPlayer.ClearQueue"}
        ),
        "AudioPlayer.PlaybackFailed": frozenset(
            {"AudioPlayer.Play", "AudioPlayer.Stop", "AudioPlayer.ClearQueue"}
        ),
    }

    @staticmethod
    def conversational(request_type: str) -> bool:
        return request_type in {"LaunchRequest", "IntentRequest", "Connections.Response"}

    @staticmethod
    def for_request(request_type: str, response: dict | None) -> dict:
        body = deepcopy(response or {})
        if not isinstance(body, dict):
            raise TypeError("Alexa response must be an object")
        if AlexaResponse.conversational(request_type) or request_type.startswith(
            "PlaybackController."
        ):
            return body
        if request_type == "CanFulfillIntentRequest":
            return (
                {"canFulfillIntent": body["canFulfillIntent"]} if "canFulfillIntent" in body else {}
            )
        allowed = AlexaResponse.CALLBACK_DIRECTIVES.get(request_type, frozenset())
        directives = [
            directive
            for directive in body.get("directives", [])
            if isinstance(directive, dict) and directive.get("type") in allowed
        ]
        return {"directives": directives} if directives else {}

    @staticmethod
    def discovery_capture_directive() -> dict:
        slot_name = "searchQuery"
        return {
            "type": "Dialog.ElicitSlot",
            "slotToElicit": slot_name,
            "updatedIntent": {
                "name": "OpenDiscoveryIntent",
                "confirmationStatus": "NONE",
                "slots": {
                    slot_name: {
                        "name": slot_name,
                        "confirmationStatus": "NONE",
                    }
                },
            },
        }

    @staticmethod
    def present_idle_next(handler_input, speak_text: str, reprompt_text: str | None = None):
        return (
            handler_input.response_builder.speak(Ssml.ssml(speak_text))
            .reprompt(Ssml.ssml(reprompt_text or Speech.IDLE_NEXT_REPROMPT))
            .add_directive(AlexaResponse.discovery_capture_directive())
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def last_resort_skill_response(request_type: str = "IntentRequest") -> dict:
        return {
            "version": "1.0",
            "response": AlexaResponse.for_request(
                request_type,
                {
                    "outputSpeech": {
                        "type": "SSML",
                        "ssml": f"<speak>{Speech.ERROR_GENERIC}</speak>",
                    },
                    "shouldEndSession": True,
                },
            ),
        }
