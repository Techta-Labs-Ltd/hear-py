from src.alexa.search_speech import SearchSpeech


def test_no_match_names_request_and_explains_how_to_retry():
    message = SearchSpeech.search_no_match("Roman Empire")

    assert "couldn't find anything matching Roman Empire" in message
    assert "different topic, creator, publication, or city" in message


def test_ambiguous_reference_message_does_not_speak_raw_alias():
    message = SearchSpeech.ambiguous_reference_message(
        "badtn",
        [
            {"name": "Barking and Dagenham Talking Newspaper"},
            {"name": "Brentwood and District Talking Newspaper"},
            {"name": "Burnley and District Talking Newspaper"},
        ],
    )
    assert message == (
        "I found more than one match for that name. "
        "First, Barking and Dagenham Talking Newspaper. "
        "Second, Brentwood and District Talking Newspaper. "
        "Third, Burnley and District Talking Newspaper. "
        "You can say the name, or first, second, or third. "
        "You can say previous to go back. "
        "Say no, none of these, or something else to return to search."
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
    assert "First, Magazine. Second, News. Third, Newspaper Worthing." in message
    assert "distinguishing part, or first, second, or third" in message


def test_ambiguity_message_announces_show_more_when_choices_remain():
    message = SearchSpeech.ambiguous_reference_message(
        "pendle voice",
        [
            {"name": "Pendle Voice Dalesman"},
            {"name": "Pendle Voice Lancashire Life"},
            {"name": "Pendle Voice Leader and Times"},
        ],
        has_more=True,
    )

    assert message.endswith(
        "To hear more choices, say show more or next. "
        "You can also say previous. "
        "Say no, none of these, or something else to return to search."
    )


def test_publication_ambiguity_announces_show_more_when_pages_remain():
    message = SearchSpeech.publication_ambiguity_message(
        [
            {"name": "Buxton Talking Song"},
            {"name": "Daily Sermons"},
            {"name": "Hexham Talking Newspapers Reading"},
        ],
        has_more=True,
    )

    assert message.endswith(
        "To hear more choices, say show more or next. "
        "You can also say previous. "
        "Say no, none of these, or something else to return to search."
    )


def test_final_ambiguity_page_does_not_offer_show_more():
    message = SearchSpeech.ambiguous_reference_message(
        "pendle voice",
        [
            {"name": "Pendle Voice Sunday People"},
            {"name": "Pendle Voice Yorkshire Life"},
        ],
        has_more=False,
    )

    assert "First, Sunday People" in message
    assert "Second, Yorkshire Life" in message
    assert "show more" not in message


def test_broad_search_intro_names_the_request_without_first_result_metadata():
    message = SearchSpeech.search_results_intro(
        37,
        {
            "query": "local transport",
            "filter": {"city": "Herne Bay", "tags": ["local-transport"]},
        },
        "content on local transport in Herne Bay",
        "Oxfordshire County Council ends free park and ride bus tickets",
        "Wallingford and District Talking Newspaper",
    )

    assert (
        message
        == "Here are 37 stories about local transport in Herne Bay. Here's the first one."
    )
    assert "Oxfordshire" not in message
    assert "Wallingford" not in message


def test_broad_category_intro_uses_filter_when_no_request_label_is_available():
    message = SearchSpeech.search_results_intro(
        4,
        {"query": "", "filter": {"categorySlugs": ["local-history"]}},
    )

    assert message == "Here are 4 stories about local history. Here's the first one."


def test_broad_category_intro_keeps_the_residual_search_terms():
    message = SearchSpeech.search_results_intro(
        9,
        {"query": "heatwave", "filter": {"categorySlugs": ["community-services"]}},
        "community services",
    )

    assert (
        message
        == "Here are 9 stories about community services and heatwave. Here's the first one."
    )


def test_location_only_intro_uses_natural_source_wording():
    message = SearchSpeech.search_results_intro(
        6,
        {"query": "", "filter": {"city": "Herne Bay"}},
        "content in Herne Bay",
    )

    assert message == "Here are 6 stories from Herne Bay. Here's the first one."


def test_source_specific_intro_keeps_first_result_context():
    message = SearchSpeech.search_results_intro(
        2,
        {"query": "", "filter": {"organizationIds": ["org-york"]}},
        "content from York Talking News",
        "Community update",
        "York Talking News",
    )

    assert message == "I found 2 stories. Now playing Community update, by York Talking News."


def test_trending_intro_does_not_attribute_the_whole_list_to_the_first_source():
    assert (
        SearchSpeech.trending_intro(8)
        == "Here are 8 trending stories. Here's the first one."
    )
