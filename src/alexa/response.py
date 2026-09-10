from __future__ import annotations

from src.alexa.speech import Speech
from src.alexa.ssml import Ssml


class AlexaResponse:
    @staticmethod
    def present_idle_next(handler_input, speak_text: str, reprompt_text: str | None = None):
        return (
            handler_input.response_builder.speak(Ssml.ssml(speak_text))
            .reprompt(Ssml.ssml(reprompt_text or Speech.IDLE_NEXT_REPROMPT))
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
