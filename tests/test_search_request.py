from __future__ import annotations

import pytest

from src.models.availability_data import AvailabilityOutcome
from src.models.availability_request import AvailabilityRequest
from src.models.search_contracts import SearchOutcome, SearchRequest
from src.utils.filters import SearchFilters


def test_search_request_normalizes_boundary_values():
    request = SearchRequest(
        query=None,
        intent=None,
        filters={"creatorIds": ["creator-1"]},
        page=-3,
        limit=0,
        max_pages=0,
    )

    assert request.query == ""
    assert request.intent == "general"
    assert request.page == 0
    assert request.limit == 1
    assert request.max_pages == 1
    assert request.filters == {"creatorIds": ["creator-1"]}


def test_search_request_does_not_share_filter_input():
    filters = {"organizationIds": ["organization-1"]}
    request = SearchRequest(filters=filters)

    filters["organizationIds"].append("organization-2")

    assert request.filters == {"organizationIds": ["organization-1"]}


def test_search_filter_owner_deduplicates_lists_and_preserves_false_and_zero():
    assert SearchFilters.clean(
        {
            "creatorIds": ["creator-1", "creator-1", "creator-2"],
            "isPublication": False,
            "latitude": 0,
            "publishedFrom": 1780272000,
            "unknown": "ignored",
        }
    ) == {
        "creatorIds": ["creator-1", "creator-2"],
        "isPublication": False,
        "latitude": 0,
        "publishedFrom": 1780272000,
    }


def test_availability_filter_owner_validates_endpoint_specific_mapping():
    assert SearchFilters.availability(
        {
            "categorySlugs": ["News", "news"],
            "location": {"city": "York", "latitude": 0, "longitude": -1.2},
        }
    ) == {
        "categorySlugs": ["news"],
        "location": {"city": "York", "latitude": 0, "longitude": -1.2},
    }


def test_availability_request_is_immutable_and_has_an_explicit_wire_mapping():
    request = AvailabilityRequest.local(
        {
            "slots": {
                "city": "Leeds",
                "countryCode": "gb",
                "isLocal": True,
            }
        },
        alexa_user_id="alexa-user",
        user_state={"listenerId": "listener-1"},
    )

    assert request.filters == {
        "city": "Leeds",
        "countryCode": "gb",
    }
    with pytest.raises(TypeError):
        request.filters["city"] = "York"
    assert request.to_search_payload() == {
        "query": "",
        "filter": {
            "city": "Leeds",
            "countryCode": "gb",
        },
        "page": 0,
        "limit": 3,
        "isLocal": True,
        "sort": "nearest",
        "alexaUserId": "alexa-user",
        "listenerId": "listener-1",
    }


@pytest.mark.parametrize("field", ("page", "limit", "max_pages"))
def test_search_request_rejects_non_numeric_pagination(field):
    with pytest.raises(ValueError):
        SearchRequest(**{field: "not-a-number"})

@pytest.mark.parametrize(
    ("response", "kind"),
    [
        ({"results": [{"contentId": "one"}]}, "success"),
        ({"results": []}, "empty"),
        ({"failed": True}, "unavailable"),
        ({"invalid": True}, "invalid"),
        ({"_publication_choices": [{"id": "publication-1"}]}, "ambiguous"),
    ],
)
def test_search_outcome_classifies_wire_responses(response, kind):
    outcome = SearchOutcome.classify(response)

    assert outcome.kind == kind
    assert outcome.is_success is (kind == "success")


def test_search_outcome_copies_result_values_and_normalizes_pagination():
    response = {
        "results": [{"contentId": "one"}],
        "total_hits": "3",
        "page": "1",
        "total_pages": "2",
    }
    outcome = SearchOutcome.classify(response)
    response["results"][0]["contentId"] = "changed"

    assert outcome.results == ({"contentId": "one"},)
    assert outcome.total_hits == 3
    assert outcome.page == 1
    assert outcome.total_pages == 2
@pytest.mark.parametrize(
    ("response", "candidates", "kind"),
    [
        ({"failed": True}, [{"id": "one"}], "unavailable"),
        ({"results": []}, [], "empty"),
        ({"results": []}, [{"id": "one"}], "success"),
    ],
)
def test_availability_outcome_classifies_terminal_result(response, candidates, kind):
    outcome = AvailabilityOutcome.classify(response, candidates)

    assert outcome.kind == kind
    assert outcome.candidates == (() if kind != "success" else ({"id": "one"},))