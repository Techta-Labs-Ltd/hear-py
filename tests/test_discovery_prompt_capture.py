from __future__ import annotations

from src.alexa.response import AlexaResponse
from src.alexa.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.models.search import Search


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

    def test_idle_question_keeps_the_typed_intent_model_active(self):
        response = AlexaResponse.present_idle_next(
            self._handler_input(),
            "What would you like to listen to?",
        )

        assert response["shouldEndSession"] is False
        assert response["directives"] == [AlexaResponse.search_query_capture_directive()]

    def test_no_content_response_recaptures_the_next_bare_discovery_reply(self):
        response = Search._build_no_content_response(self._handler_input())

        assert response["shouldEndSession"] is False
        assert response["directives"] == [AlexaResponse.search_query_capture_directive()]

    def test_empty_search_response_recaptures_the_next_bare_discovery_reply(self):
        response = Search._build_search_outcome_response(
            self._handler_input(),
            {"failed": False, "_search_payload": {"query": "Sevenoaks"}},
        )

        assert response["shouldEndSession"] is False
        assert response["directives"] == [AlexaResponse.search_query_capture_directive()]

    def test_capture_directive_reuses_the_existing_search_query_slot(self):
        assert AlexaResponse.search_query_capture_directive() == {
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
