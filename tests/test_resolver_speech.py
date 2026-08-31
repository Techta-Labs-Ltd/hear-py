from src.alexa.search_speech import SearchSpeech


def test_no_match_names_request_and_explains_how_to_retry():
    message = SearchSpeech.search_no_match("Roman Empire")

    assert "couldn't find anything matching Roman Empire" in message
    assert "different topic, creator, publication, or place" in message


def test_ambiguous_reference_message_does_not_speak_raw_alias():
    message = SearchSpeech.ambiguous_reference_message(
        "badtn",
        [
            {"name": "Barking and Dagenham Talking Newspaper"},
            {"name": "Brentwood and District Talking Newspaper"},
            {"name": "Burnley and District Talking Newspaper"},
        ],
    )
    assert (
        message
        == "I found more than one match for that name. Did you mean Barking and Dagenham Talking Newspaper, Brentwood and District Talking Newspaper, or Burnley and District Talking Newspaper?"
    )
    assert "badtn" not in message.lower()


def test_common_ambiguity_prefix_requests_distinguishing_words():
    message = SearchSpeech.ambiguous_reference_message(
        "sussex",
        [
            {"name": "Sussex Coast Talking Magazine"},
            {"name": "Sussex Coast Talking News"},
            {"name": "Sussex Coast Talking Newspaper Worthing"},
        ],
    )
    assert "beginning Sussex Coast Talking" in message
    assert "Magazine, News, or Newspaper Worthing" in message
