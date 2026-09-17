from datetime import datetime
from zoneinfo import ZoneInfo

from src.utils.search_payload import SearchPayload


def test_local_search_does_not_add_saved_location_to_the_filter(mock_handler_input):
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
    assert "sort" not in payload
    assert payload["filter"] == {"city": "York"}


def test_local_search_does_not_create_a_filter_from_saved_location(
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
    assert "sort" not in payload
    assert "filter" not in payload


def test_local_search_does_not_add_saved_coordinates(mock_handler_input):
    payload = SearchPayload.build(
        "user-1",
        {"latitude": 53.789, "longitude": -2.248},
        q="",
        nlp_filter={"isLocal": True},
    )
    assert "filter" not in payload
    assert "sort" not in payload


def test_different_named_city_uses_city_coordinates_without_a_default_sort(
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
    assert "sort" not in payload


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


def test_false_boolean_filters_are_omitted_from_search(mock_handler_input):
    payload = SearchPayload.build(
        "user-1",
        q="",
        nlp_filter={
            "organizationIds": ["organization-1"],
            "isPublication": False,
            "isLocal": False,
        },
    )

    assert payload["filter"] == {"organizationIds": ["organization-1"]}


def test_publication_dates_are_nested_in_search_filter(mock_handler_input):
    payload = SearchPayload.build(
        "user-1",
        q="",
        sort="latest",
        nlp_filter={"publishedFrom": 1780272000, "publishedTo": 1782864000},
    )
    assert payload["filter"] == {"publishedFrom": 1780272000, "publishedTo": 1782864000}


def test_search_date_labels_keep_the_local_uk_calendar_day():
    zone = ZoneInfo("Europe/London")
    start = int(datetime(2026, 9, 17, tzinfo=zone).timestamp())
    end = int(datetime(2026, 9, 18, tzinfo=zone).timestamp())

    assert SearchPayload.resolved_request_label(
        {"searchPlan": {"filter": {"publishedFrom": start, "publishedTo": end}}}
    ) == "content published on 17 September 2026"
