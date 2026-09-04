from src.alexa.help import HelpSpeech
from src.controllers.system import HelpIntentHandler


class HelpCommandTestSupport:
    @staticmethod
    def intent(handler_input):
        handler_input.request_envelope["request"] = {
            "type": "IntentRequest",
            "intent": {"name": "AMAZON.HelpIntent", "slots": {}},
        }
        builder = handler_input.response_builder
        builder.speak.return_value = builder
        builder.reprompt.return_value = builder
        builder.with_simple_card.return_value = builder
        builder.set_should_end_session.return_value = builder
        return handler_input


def test_help_command_gives_a_complete_uk_english_voice_guide(mock_handler_input):
    handler_input = HelpCommandTestSupport.intent(mock_handler_input)

    response = HelpIntentHandler().handle(handler_input)

    spoken = handler_input.response_builder.speak.call_args.args[0]
    assert "play the latest news" in spoken
    assert "talking newspaper" in spoken
    assert "pause to keep your place" in spoken
    assert "next or skip" in spoken
    assert "previous" in spoken
    assert "rewind 30 seconds" in spoken
    assert "first speed for 0.5 times" in spoken
    assert "second for 0.75" in spoken
    assert "third for normal speed" in spoken
    assert "fourth for 1.25" in spoken
    assert "fifth for 1.5" in spoken
    assert "sixth for 2 times speed" in spoken
    assert "Available speeds may vary by recording" in spoken
    assert "pause it and then say" in spoken
    assert "what's this about" in spoken
    assert "follow or unfollow" in spoken
    assert "notifications on or off" in spoken
    assert "change my location" in spoken
    assert "set up my account" in spoken
    assert response is handler_input.response_builder.response


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
