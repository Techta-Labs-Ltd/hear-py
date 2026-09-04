from src.utils.search_payload import SearchPayload


def test_saved_city_uses_registered_listener_radius(mock_handler_input):
    payload = SearchPayload.build(
        "user-1",
        {
            "userCity": "York",
            "locality": "York",
            "latitude": 53.959,
            "longitude": -1.081,
        },
        q="",
        nlp_filter={"city": "York", "isLocal": True},
    )
    assert payload["isLocal"] is True
    assert payload["sort"] == "nearest"
    assert payload["filter"] == {
        "city": "York",
        "latitude": 53.959,
        "longitude": -1.081,
    }


def test_my_city_without_named_facet_uses_registered_listener_radius(
    mock_handler_input,
):
    payload = SearchPayload.build(
        "user-1",
        {
            "userCity": "Swindon",
            "locality": "Swindon",
            "latitude": 51.5558,
            "longitude": -1.7797,
        },
        q="",
        nlp_filter={"isLocal": True},
    )
    assert payload["isLocal"] is True
    assert payload["sort"] == "nearest"
    assert payload["filter"] == {
        "city": "Swindon",
        "latitude": 51.5558,
        "longitude": -1.7797,
    }


def test_coordinate_only_location_is_used_for_local_search(mock_handler_input):
    payload = SearchPayload.build(
        "user-1",
        {"latitude": 53.789, "longitude": -2.248},
        q="",
        nlp_filter={"isLocal": True},
    )
    assert payload["filter"] == {"latitude": 53.789, "longitude": -2.248}
    assert payload["sort"] == "nearest"


def test_different_named_city_uses_city_coordinates_and_nearest_sort(
    mock_handler_input,
):
    payload = SearchPayload.build(
        "user-1",
        {"userCity": "Swindon", "locality": "Swindon"},
        q="",
        nlp_filter={
            "city": "Manchester",
            "latitude": 53.4808,
            "longitude": -2.2426,
            "isLocal": True,
        },
    )
    assert payload["isLocal"] is True
    assert payload["filter"] == {
        "city": "Manchester",
        "latitude": 53.4808,
        "longitude": -2.2426,
    }
    assert payload["sort"] == "nearest"


def test_absent_query_is_serialized_as_an_empty_string(mock_handler_input):
    payload = SearchPayload.build("user-1", q=None)
    assert payload["query"] == ""
    assert payload["limit"] == 3


def test_resolver_page_size_is_normalized_to_three():
    payload = SearchPayload.from_resolution(
        {"searchPayload": {"query": "news", "page": 0, "limit": 20}},
        3,
    )

    assert payload["limit"] == 3


def test_publication_filter_is_nested_in_search_filter(mock_handler_input):
    payload = SearchPayload.build(
        "user-1", q="", sort="trending", nlp_filter={"isPublication": True}
    )
    assert payload["filter"] == {"isPublication": True}
    assert payload["sort"] == "trending"


def test_publication_dates_are_nested_in_search_filter(mock_handler_input):
    payload = SearchPayload.build(
        "user-1",
        q="",
        sort="latest",
        nlp_filter={"publishedFrom": 1780272000, "publishedTo": 1782864000},
    )
    assert payload["filter"] == {"publishedFrom": 1780272000, "publishedTo": 1782864000}
