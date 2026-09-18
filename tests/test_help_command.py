from src.alexa.dialog import DialogStateManager
from src.alexa.help import HelpSpeech
from src.controllers.system import HelpConfirmationHandler, HelpIntentHandler


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


def test_help_command_gives_a_short_guide_then_requests_a_yes_or_no_answer(mock_handler_input):
    handler_input = HelpCommandTestSupport.intent(mock_handler_input)

    response = HelpIntentHandler().handle(handler_input)

    spoken = handler_input.response_builder.speak.call_args.args[0]
    assert "Welcome to Hear" in spoken
    assert "talking newspaper" in spoken
    assert "city" in spoken
    assert "find content about the Roman Empire" in spoken
    assert "what's trending to hear popular content from across Hear" in spoken
    assert "play recommendations for something chosen for you" in spoken
    assert "Would you like to hear more? Say yes or no" in spoken
    assert "what's new" not in spoken
    assert "Talking News Federation" not in spoken
    assert "play local news in Swindon" not in spoken
    assert "publication Morning Update" not in spoken
    assert "rewind 30 seconds" not in spoken
    assert DialogStateManager.get_active(handler_input)["type"] == "help"
    assert response is handler_input.response_builder.response


def test_help_confirmation_yes_returns_the_complete_guide(mock_handler_input):
    handler_input = HelpCommandTestSupport.intent(mock_handler_input)
    HelpIntentHandler().handle(handler_input)
    handler_input.request_envelope["request"]["intent"]["name"] = "AMAZON.YesIntent"

    handler = HelpConfirmationHandler()

    assert handler.can_handle(handler_input) is True
    handler.handle(handler_input)

    spoken = handler_input.response_builder.speak.call_args.args[0]
    assert "pause to keep your place" in spoken
    assert "rewind 30 seconds" not in spoken
    assert "fast forward 2 minutes" not in spoken
    assert "play faster, play slower, increase speed, reduce speed, or normal speed" in spoken
    assert "follow or unfollow" in spoken
    assert "What would you like to hear?" in spoken
    assert DialogStateManager.get_active(handler_input) is None


def test_help_confirmation_no_returns_to_idle_listening(mock_handler_input):
    handler_input = HelpCommandTestSupport.intent(mock_handler_input)
    HelpIntentHandler().handle(handler_input)
    handler_input.request_envelope["request"]["intent"]["name"] = "AMAZON.NoIntent"

    handler = HelpConfirmationHandler()

    assert handler.can_handle(handler_input) is True
    handler.handle(handler_input)

    spoken = handler_input.response_builder.speak.call_args.args[0]
    assert "What would you like to listen to?" in spoken
    assert DialogStateManager.get_active(handler_input) is None


def test_help_command_adds_a_scannable_complete_guide_card(mock_handler_input):
    handler_input = HelpCommandTestSupport.intent(mock_handler_input)

    HelpIntentHandler().handle(handler_input)

    card_args = handler_input.response_builder.with_simple_card.call_args.args
    card_text = HelpSpeech.card_text("development")
    assert card_args == (HelpSpeech.CARD_TITLE, card_text)
    assert "organisation" in card_text
    assert "Rewind 30 seconds" not in card_text
    assert "Rate this recording" in card_text
    assert "Hear my updates" in card_text
    assert "Set up my account" in card_text
    assert "What's new" not in card_text
    assert "Talking News Federation" not in card_text
    assert "Play local news in Swindon" not in card_text
    assert "Play the publication Morning Update" not in card_text
    assert "Rewind 30 seconds" not in card_text
    assert "Fast forward 2 minutes" not in card_text
    assert "Increase speed" in card_text
    assert "Reduce speed" in card_text
    handler_input.response_builder.set_should_end_session.assert_called_once_with(False)
