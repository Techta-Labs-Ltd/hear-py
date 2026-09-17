from src.alexa.dialog import DialogStateManager
from src.alexa.help import HelpSpeech
from src.controllers.system import HelpIntentHandler, HelpMoreIntentHandler


class HelpCommandTestSupport:
    @staticmethod
    def intent(handler_input, intent_name: str = "AMAZON.HelpIntent"):
        handler_input.request_envelope["request"] = {
            "type": "IntentRequest",
            "intent": {"name": intent_name, "slots": {}},
        }
        builder = handler_input.response_builder
        builder.speak.return_value = builder
        builder.reprompt.return_value = builder
        builder.with_simple_card.return_value = builder
        builder.set_should_end_session.return_value = builder
        return handler_input


def test_help_command_gives_a_short_guide_then_invites_more(mock_handler_input):
    handler_input = HelpCommandTestSupport.intent(mock_handler_input)

    response = HelpIntentHandler().handle(handler_input)

    spoken = handler_input.response_builder.speak.call_args.args[0]
    assert "Welcome to Hear" in spoken
    assert "talking newspaper" in spoken
    assert "Say more to hear the full guide" in spoken
    assert "rewind 30 seconds" not in spoken
    assert DialogStateManager.get_active(handler_input)["type"] == "help"
    assert response is handler_input.response_builder.response


def test_help_more_returns_the_complete_guide(mock_handler_input):
    handler_input = HelpCommandTestSupport.intent(mock_handler_input)
    HelpIntentHandler().handle(handler_input)
    handler_input.request_envelope["request"]["intent"]["name"] = "AMAZON.NextIntent"

    handler = HelpMoreIntentHandler()

    assert handler.can_handle(handler_input) is True
    handler.handle(handler_input)

    spoken = handler_input.response_builder.speak.call_args.args[0]
    assert "pause to keep your place" in spoken
    assert "rewind 30 seconds" in spoken
    assert "follow or unfollow" in spoken
    assert DialogStateManager.get_active(handler_input) is None


def test_help_command_adds_a_scannable_complete_guide_card(mock_handler_input):
    handler_input = HelpCommandTestSupport.intent(mock_handler_input)

    HelpIntentHandler().handle(handler_input)

    card_args = handler_input.response_builder.with_simple_card.call_args.args
    card_text = HelpSpeech.card_text("development")
    assert card_args == (HelpSpeech.CARD_TITLE, card_text)
    assert "organisation" in card_text
    assert "Rewind 30 seconds" in card_text
    assert "Rate this recording" in card_text
    assert "Hear my updates" in card_text
    assert "Set up my account" in card_text
    handler_input.response_builder.set_should_end_session.assert_called_once_with(False)
