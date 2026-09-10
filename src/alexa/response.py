from __future__ import annotations

from src.alexa.speech import Speech
from src.alexa.ssml import Ssml


class AlexaResponse:
    @staticmethod
    def typed_discovery_directive() -> dict:
        slot_name = "topic"
        return {
            "type": "Dialog.ElicitSlot",
            "slotToElicit": slot_name,
            "updatedIntent": {
                "name": "CarrierlessDiscoveryIntent",
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
            .add_directive(AlexaResponse.typed_discovery_directive())
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def last_resort_skill_response() -> dict:
        return {
            "version": "1.0",
            "response": {
                "outputSpeech": {
                    "type": "SSML",
                    "ssml": f"<speak>{Speech.ERROR_GENERIC}</speak>",
                },
                "shouldEndSession": True,
            },
        }
