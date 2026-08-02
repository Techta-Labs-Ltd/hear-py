from src.utils.search_filters import SearchPayload


def test_saved_city_uses_registered_listener_radius(mock_handler_input):
    payload = SearchPayload.build(
        mock_handler_input,
        {"userCity": "Swindon", "locality": "Swindon"},
        q="",
        nlp_filter={"city": "Swindon", "isLocal": True},
    )

    assert payload["isLocal"] is True
    assert payload["sort"] == "nearest"
    assert "filter" not in payload


def test_my_city_without_named_facet_uses_registered_listener_radius(
    mock_handler_input,
):
    payload = SearchPayload.build(
        mock_handler_input,
        {"userCity": "Swindon", "locality": "Swindon"},
        q="",
        nlp_filter={"isLocal": True},
    )

    assert payload["isLocal"] is True
    assert payload["sort"] == "nearest"
    assert "filter" not in payload


def test_different_named_city_uses_exact_city_not_listener_radius(
    mock_handler_input,
):
    payload = SearchPayload.build(
        mock_handler_input,
        {"userCity": "Swindon", "locality": "Swindon"},
        q="",
        nlp_filter={"city": "Manchester", "isLocal": True},
    )

    assert payload["isLocal"] is False
    assert payload["filter"] == {"city": "Manchester"}
    assert "sort" not in payload


def test_absent_query_is_serialized_as_an_empty_string(mock_handler_input):
    payload = SearchPayload.build(mock_handler_input, q=None)

    assert payload["query"] == ""
