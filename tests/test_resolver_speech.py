from src.utils.speech import ambiguous_reference_message


def test_ambiguous_reference_message_does_not_speak_raw_alias():
    message = ambiguous_reference_message("badtn", [
        {"name": "Barking and Dagenham Talking Newspaper"},
        {"name": "Brentwood and District Talking Newspaper"},
        {"name": "Burnley and District Talking Newspaper"},
    ])

    assert message == (
        "I found more than one match for that name. Did you mean "
        "Barking and Dagenham Talking Newspaper, "
        "Brentwood and District Talking Newspaper, or "
        "Burnley and District Talking Newspaper?"
    )
    assert "badtn" not in message.lower()
