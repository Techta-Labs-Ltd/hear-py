import pytest

from src.alexa.dialog import DialogStateManager
from src.alexa.intent_dispatch import IntentDispatcher
from src.models.user import User
from src.utils.discovery_examples import DiscoveryExamples


@pytest.mark.parametrize("name", ["York Talking News", "Tynedale Talking Newspaper"])
def test_fallback_randomises_canonical_name_and_reuses_it_in_reprompt(
    monkeypatch, mock_handler_input, name
):
    def choose(names):
        assert name in names
        return name

    monkeypatch.setattr("src.utils.discovery_examples.random.choice", choose)
    mock_handler_input.response_builder.speak.return_value = mock_handler_input.response_builder
    mock_handler_input.response_builder.reprompt.return_value = mock_handler_input.response_builder
    IntentDispatcher._missing_suggestion_response(mock_handler_input)
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    reprompt = mock_handler_input.response_builder.reprompt.call_args.args[0]
    assert f"You can say play {name}, or say the name of your city to begin listening." in spoken
    assert f"play {name}" in reprompt
    assert "say the name of your city to begin listening" in reprompt


def test_examples_use_newspaper_names_from_model():
    assert set(DiscoveryExamples.newspaper_names()) == {
        "York Talking News",
        "Tynedale Talking Newspaper",
    }


def test_other_dialogues_keep_their_expiry(monkeypatch, mock_handler_input):
    monkeypatch.setattr("src.alexa.dialog.time.time", lambda: 1000)
    DialogStateManager.activate(mock_handler_input, "resume")
    assert User.snapshot(mock_handler_input)["activeDialog"]["expiresAt"] == 1600
    DialogStateManager.activate(mock_handler_input, "feedback", ttl_seconds=120)
    assert User.snapshot(mock_handler_input)["activeDialog"]["expiresAt"] == 1120
