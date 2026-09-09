from __future__ import annotations

from src.alexa.response import AlexaResponse
from src.alexa.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder


class TestDiscoveryPromptCapture:
    @staticmethod
    def _handler_input() -> HandlerInput:
        envelope = AttrDict(
            {
                "version": "1.0",
                "context": {"System": {"user": {"userId": "test-user"}}},
                "request": {"type": "LaunchRequest", "locale": "en-GB"},
            }
        )
        return HandlerInput(envelope, AttributesManager(envelope), None, ResponseBuilder())

    def test_idle_question_elicits_a_bare_discovery_reply(self):
        response = AlexaResponse.present_idle_next(
            self._handler_input(),
            "What would you like to listen to?",
        )

        assert response["shouldEndSession"] is False
        assert response["directives"] == [AlexaResponse.discovery_capture_directive()]

    def test_capture_switches_to_the_carrierless_intent(self):
        assert AlexaResponse.discovery_capture_directive() == {
            "type": "Dialog.ElicitSlot",
            "slotToElicit": "searchQuery",
            "updatedIntent": {
                "name": "SearchContentIntent",
                "confirmationStatus": "NONE",
                "slots": {
                    "searchQuery": {
                        "name": "searchQuery",
                        "confirmationStatus": "NONE",
                    }
                },
            },
        }
