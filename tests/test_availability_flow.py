from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.alexa.availability_speech import AvailabilitySpeech
from src.alexa.response import AlexaResponse
from src.alexa.runtime import AttrDict, ResponseBuilder
from src.constants.state import StateSchema
from src.models.availability import Availability
from src.models.availability_data import AvailabilityData
from src.models.dialog import DialogStateManager
from src.models.user import User


class AvailabilityTestSupport:
    @staticmethod
    def intent(handler_input, name: str, slots: dict | None = None):
        handler_input.request_envelope = AttrDict(handler_input.request_envelope)
        handler_input.request_envelope.request = AttrDict(
            {
                "type": "IntentRequest",
                "requestId": "availability-request",
                "intent": {"name": name, "slots": slots or {}},
            }
        )
        handler_input.response_builder = ResponseBuilder()
        return handler_input

    @staticmethod
    def dependencies(availability_result: dict, search_result: dict | None = None):
        return SimpleNamespace(
            heara=SimpleNamespace(
                availability=AsyncMock(return_value=availability_result),
                search=AsyncMock(
                    return_value=search_result or {"failed": False, "results": [], "total_hits": 0}
                ),
            ),
            progressive=SimpleNamespace(send=AsyncMock(return_value=True)),
        )

    @staticmethod
    def speech(response: dict) -> str:
        return response["outputSpeech"]["ssml"]


@pytest.mark.asyncio
async def test_something_else_leaves_availability_choices_and_returns_to_search(
    mock_handler_input,
):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, "DismissChoicesIntent")
    context = {
        "kind": "publication",
        "candidates": [{"type": "publication", "id": "pub-1", "name": "Local News"}],
        "displayedCandidates": [
            {"type": "publication", "id": "pub-1", "name": "Local News"}
        ],
    }
    DialogStateManager.activate(handler_input, "availability", context=context)
    deps = AvailabilityTestSupport.dependencies({"failed": False})

    response = await Availability(deps=deps).handle_dialog(handler_input)

    assert "What would you like to listen to instead?" in AvailabilityTestSupport.speech(response)
    assert response["shouldEndSession"] is False
    assert response["directives"] == [AlexaResponse.typed_discovery_directive()]
    assert User.snapshot(handler_input)["activeDialog"] is None


@pytest.mark.asyncio
async def test_no_leaves_multiple_availability_choices_and_returns_to_search(
    mock_handler_input,
):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, "AMAZON.NoIntent")
    candidates = [
        {"type": "publication", "id": "pub-1", "name": "First Publication"},
        {"type": "publication", "id": "pub-2", "name": "Second Publication"},
    ]
    DialogStateManager.activate(
        handler_input,
        "availability",
        context={
            "kind": "publication",
            "candidates": candidates,
            "displayedCandidates": candidates,
        },
    )
    deps = AvailabilityTestSupport.dependencies({"failed": False})

    response = await Availability(deps=deps).handle_dialog(handler_input)

    assert "What would you like to listen to instead?" in AvailabilityTestSupport.speech(response)
    assert response["shouldEndSession"] is False
    assert response["directives"] == [AlexaResponse.typed_discovery_directive()]
    assert User.snapshot(handler_input)["activeDialog"] is None


def test_availability_accepts_one_creator_and_one_organization():
    assert AvailabilityData.source_from_resolution(
        {
            "searchPayload": {
                "filter": {
                    "creatorIds": ["creator-1"],
                    "organizationIds": ["org-1"],
                }
            },
            "resolvedEntities": [
                {
                    "type": "creator",
                    "id": "creator-1",
                    "canonicalValue": "A Reader",
                }
            ],
        }
    ) == {"type": "creator", "id": "creator-1", "name": "A Reader"}
    assert (
        AvailabilityData.source_from_resolution(
            {"searchPayload": {"filter": {"creatorIds": ["creator-1", "creator-2"]}}}
        )
        is None
    )
    assert AvailabilityData.source_from_resolution(
        {
            "searchPayload": {"filter": {"organizationIds": ["org-1"]}},
            "resolvedEntities": [
                {
                    "type": "organization",
                    "id": "org-1",
                    "canonicalValue": "Redcar Talking Newspaper",
                }
            ],
        }
    ) == {
        "type": "organization",
        "id": "org-1",
        "name": "Redcar Talking Newspaper",
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"query": "", "filter": {"organizationIds": ["org-1"]}}, "source"),
        ({"query": "", "filter": {"creatorIds": ["creator-1"]}}, "source"),
        ({"query": "", "filter": {"city": "Swindon"}}, "location"),
        (
            {
                "query": "",
                "filter": {"city": "Swindon", "organizationIds": ["org-1"]},
            },
            "source",
        ),
        (
            {
                "query": "",
                "filter": {"city": "Swindon", "creatorIds": ["creator-1"]},
            },
            "source",
        ),
        (
            {
                "query": "",
                "filter": {"categorySlugs": ["news"], "organizationIds": ["org-1"]},
            },
            None,
        ),
        (
            {"query": "", "filter": {"city": "Swindon", "categorySlugs": ["news"]}},
            None,
        ),
        ({"query": "heatwave", "filter": {"organizationIds": ["org-1"]}}, None),
        (
            {"query": "", "filter": {"creatorIds": ["creator-1"], "tags": ["news"]}},
            None,
        ),
        (
            {"query": "", "filter": {"city": "Swindon", "publishedFrom": 1788393600}},
            None,
        ),
        (
            {
                "query": "",
                "filter": {
                    "creatorIds": ["creator-1"],
                    "organizationIds": ["org-1"],
                },
            },
            "source",
        ),
        ({"query": "council", "filter": {}}, None),
    ],
)
def test_availability_scope_accepts_supported_filter_combinations(payload, expected):
    assert AvailabilityData.request_scope(payload) == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"filter": {"city": "Swindon"}},
            {"location": {"city": "Swindon"}},
        ),
        (
            {"filter": {"creatorIds": ["creator-1"]}},
            {"creatorId": "creator-1"},
        ),
        (
            {"filter": {"organizationIds": ["org-1"]}},
            {"organizationId": "org-1"},
        ),
        (
            {"filter": {"creatorIds": ["creator-1"], "organizationIds": ["org-1"]}},
            {"creatorId": "creator-1", "organizationId": "org-1"},
        ),
        (
            {"filter": {"city": "Swindon", "creatorIds": ["creator-1"]}},
            {"creatorId": "creator-1", "location": {"city": "Swindon"}},
        ),
        (
            {"filter": {"city": "Swindon", "organizationIds": ["org-1"]}},
            {"organizationId": "org-1", "location": {"city": "Swindon"}},
        ),
        (
            {
                "filter": {
                    "city": "Swindon",
                    "creatorIds": ["creator-1"],
                    "organizationIds": ["org-1"],
                }
            },
            {
                "creatorId": "creator-1",
                "organizationId": "org-1",
                "location": {"city": "Swindon"},
            },
        ),
    ],
)
def test_availability_filter_serializes_supported_combinations(payload, expected):
    assert AvailabilityData.availability_filter(payload, {}) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {
            "query": "",
            "filter": {"categorySlugs": ["news"], "organizationIds": ["org-1"]},
        },
        {"query": "", "filter": {"city": "Swindon", "categorySlugs": ["news"]}},
        {"query": "heatwave", "filter": {"creatorIds": ["creator-1"]}},
    ],
)
async def test_mixed_searches_bypass_availability(mock_handler_input, payload):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, "PlayContentIntent")
    deps = AvailabilityTestSupport.dependencies({"failed": False})

    response = await Availability(deps=deps).handle_resolution(
        handler_input,
        {"intent": "search", "searchPayload": payload},
        payload,
        "requested content",
    )

    assert response is None
    deps.heara.availability.assert_not_awaited()


@pytest.mark.asyncio
async def test_location_and_one_organization_preserves_both_availability_filters(
    mock_handler_input,
):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, "AMAZON.YesIntent")
    payload = {
        "query": "",
        "filter": {"city": "Swindon", "organizationIds": ["org-1"]},
    }
    deps = AvailabilityTestSupport.dependencies(
        {
            "failed": False,
            "publication_count": 1,
            "standalone_track_count": 0,
            "publications": [{"type": "publication", "id": "pub-1", "name": "Local News"}],
        }
    )

    await Availability(deps=deps).handle_resolution(
        handler_input,
        {
            "intent": "organization",
            "searchPayload": payload,
            "resolvedEntities": [
                {"type": "organization", "id": "org-1", "canonicalValue": "Local Voice"}
            ],
        },
        payload,
        "Local Voice",
    )

    assert deps.heara.availability.await_args.args[0] == {
        "filter": {
            "organizationId": "org-1",
            "location": {"city": "Swindon"},
        },
        "alexaUserId": "amzn1.ask.account.TEST",
        "page": 0,
        "limit": 3,
    }


@pytest.mark.asyncio
async def test_general_search_does_not_call_availability(mock_handler_input):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, "PlayContentIntent")
    deps = AvailabilityTestSupport.dependencies({"failed": False})

    response = await Availability(deps=deps).handle_resolution(
        handler_input,
        {
            "intent": "search",
            "searchPayload": {
                "query": "local council news",
                "filter": {"tags": ["news"]},
            },
        },
        {"query": "local council news", "filter": {"tags": ["news"]}},
        "local council news",
    )

    assert response is None
    deps.heara.availability.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_availability_offers_organizations_and_creators(mock_handler_input):
    handler_input = AvailabilityTestSupport.intent(
        mock_handler_input,
        "PlayLocalIntent",
        {"localQuery": {"name": "localQuery", "value": "Swindon"}},
    )
    handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "userCity": "Swindon",
        "latitude": 51.56,
        "longitude": -1.78,
    }
    deps = AvailabilityTestSupport.dependencies(
        {
            "failed": False,
            "page": 0,
            "total_pages": 1,
            "has_more": False,
            "organizations": [
                {"type": "organization", "id": "org-1", "name": "Talking News Federation"}
            ],
            "creators": [{"type": "creator", "id": "creator-1", "name": "Adeshina Ayomide"}],
        }
    )

    response = await Availability(deps=deps).begin_local(
        handler_input,
        {"intent": "local", "slots": {"city": "Swindon", "isLocal": True}},
    )

    deps.heara.availability.assert_awaited_once()
    body = deps.heara.availability.await_args.args[0]
    assert body["filter"]["location"] == {
        "city": "Swindon",
        "latitude": 51.56,
        "longitude": -1.78,
    }
    assert body["alexaUserId"] == "amzn1.ask.account.TEST"
    assert "isLocal" not in body
    speech = AvailabilityTestSupport.speech(response)
    assert "Here are the talking newspapers and creators closest to Swindon" in speech
    assert "Here are the local sources I found" not in speech
    assert "First, Talking News Federation" in speech
    assert "Second, Adeshina Ayomide" in speech
    assert "You can say first or second" in speech
    assert "more sources" not in speech
    assert "previous" not in speech
    assert response["shouldEndSession"] is False
    assert DialogStateManager.get_active(handler_input)["type"] == "availability"


@pytest.mark.asyncio
async def test_empty_local_availability_stops_without_search_or_playback_mutation(
    mock_handler_input,
):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, "AMAZON.YesIntent")
    playback_state = {
        "activePlayback": {"token": "existing-token", "offsetInMilliseconds": 42000},
        "playbackQueue": {"items": [{"contentId": "existing-track"}]},
        "lastToken": "existing-token",
        "lastOffsetMs": 42000,
    }
    User.update(handler_input, playback_state)
    before = {key: User.snapshot(handler_input).get(key) for key in playback_state}
    deps = AvailabilityTestSupport.dependencies(
        {
            "failed": False,
            "page": 0,
            "total_pages": 0,
            "has_more": False,
            "total": 0,
            "organizations": [],
            "creators": [],
            "publications": [],
            "publication_count": 0,
            "standalone_track_count": 0,
        }
    )

    response = await Availability(deps=deps).begin_local(
        handler_input,
        {
            "intent": "local",
            "requestedLocation": True,
            "slots": {
                "city": "Shalfleet",
                "countryCode": "gb",
                "latitude": 50.7011,
                "longitude": -1.4152,
                "isLocal": True,
            },
        },
    )

    assert deps.heara.availability.await_args.args[0] == {
        "filter": {
            "location": {
                "city": "Shalfleet",
                "countryCode": "gb",
                "latitude": 50.7011,
                "longitude": -1.4152,
            }
        },
        "alexaUserId": "amzn1.ask.account.TEST",
        "page": 0,
        "limit": 3,
    }
    deps.heara.search.assert_not_awaited()
    assert "couldn't find any content in Shalfleet right now" in AvailabilityTestSupport.speech(
        response
    )
    assert response["directives"] == [AlexaResponse.typed_discovery_directive()]
    after = User.snapshot(handler_input)
    assert {key: after.get(key) for key in playback_state} == before


@pytest.mark.asyncio
async def test_failed_local_request_uses_listener_language_and_city(mock_handler_input):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, "AMAZON.YesIntent")
    deps = AvailabilityTestSupport.dependencies({"failed": True})

    response = await Availability(deps=deps).begin_local(
        handler_input,
        {
            "intent": "local",
            "requestedLocation": True,
            "slots": {"city": "Everton", "isLocal": True},
        },
    )

    speech = AvailabilityTestSupport.speech(response)
    assert "had trouble finding content in Everton just now" in speech
    assert "availability" not in speech.casefold()
    assert response["directives"] == [AlexaResponse.typed_discovery_directive()]
    deps.heara.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_source_availability_stops_without_search(mock_handler_input):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, "AMAZON.YesIntent")
    deps = AvailabilityTestSupport.dependencies(
        {
            "failed": False,
            "publication_count": 0,
            "standalone_track_count": 0,
            "publications": [],
        }
    )

    response = await Availability(deps=deps)._begin_source(
        handler_input,
        {"type": "organization", "id": "org-1", "name": "Local Voice"},
        {"query": "", "filter": {"organizationIds": ["org-1"]}},
    )

    deps.heara.search.assert_not_awaited()
    assert "couldn't find any content from Local Voice right now" in AvailabilityTestSupport.speech(
        response
    )
    assert response["directives"] == [AlexaResponse.typed_discovery_directive()]


@pytest.mark.asyncio
async def test_failed_availability_stops_without_search(mock_handler_input):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, "AMAZON.YesIntent")
    deps = AvailabilityTestSupport.dependencies({"failed": True})

    response = await Availability(deps=deps)._begin_source(
        handler_input,
        {"type": "creator", "id": "creator-1", "name": "A Reader"},
        {"query": "", "filter": {"creatorIds": ["creator-1"]}},
    )

    deps.heara.search.assert_not_awaited()
    speech = AvailabilityTestSupport.speech(response)
    assert "had trouble finding content from A Reader just now" in speech
    assert "availability" not in speech.casefold()
    assert response["directives"] == [AlexaResponse.typed_discovery_directive()]


def test_source_candidates_keep_same_name_in_distinct_domains():
    candidates = AvailabilityData.source_candidates(
        {
            "organizations": [{"type": "organization", "id": "org-1", "name": "Community Voice"}],
            "creators": [{"type": "creator", "id": "creator-1", "name": "Community Voice"}],
        }
    )
    assert [(item["type"], item["id"]) for item in candidates] == [
        ("organization", "org-1"),
        ("creator", "creator-1"),
    ]


@pytest.mark.parametrize(
    ("candidate_type", "expected"),
    [
        ("organization", "Here are the talking newspapers closest to York."),
        ("creator", "Here are the creators closest to York."),
    ],
)
def test_local_choice_opening_names_the_returned_domain(candidate_type, expected):
    speech = AvailabilitySpeech.local_source_choices(
        [
            {"type": candidate_type, "id": "one", "name": "First Result"},
            {"type": candidate_type, "id": "two", "name": "Second Result"},
        ],
        requested_city="York",
    )
    assert expected in speech


def test_supplied_location_filter_preserves_country_and_does_not_mix_saved_coordinates():
    payload = {
        "filter": {
            "city": "Liverpool",
            "countryCode": "gb",
        }
    }
    store = {
        "userCity": "Swindon",
        "latitude": 51.56,
        "longitude": -1.78,
    }

    assert AvailabilityData.location_from_payload(payload, store) == {
        "city": "Liverpool",
        "countryCode": "gb",
    }


def test_coordinate_only_location_filter_is_preserved():
    payload = {"filter": {"latitude": 53.4072, "longitude": -2.9917}}

    assert AvailabilityData.location_from_payload(payload, {}) == {
        "latitude": 53.4072,
        "longitude": -2.9917,
    }


@pytest.mark.asyncio
async def test_requested_city_source_does_not_say_near_you(mock_handler_input):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, "AMAZON.YesIntent")
    deps = AvailabilityTestSupport.dependencies(
        {
            "failed": False,
            "page": 0,
            "total_pages": 1,
            "has_more": False,
            "organizations": [
                {
                    "type": "organization",
                    "id": "org-liverpool",
                    "name": "Liverpool Talking Newspaper",
                }
            ],
            "creators": [],
        }
    )
    resolution = {
        "intent": "search",
        "slots": {"city": "Liverpool", "placeName": "Liverpool", "isLocal": True},
    }
    payload = {"query": "", "filter": {"city": "Liverpool"}}

    response = await Availability(deps=deps).handle_resolution(
        handler_input, resolution, payload, "content in Liverpool"
    )

    speech = AvailabilityTestSupport.speech(response)
    assert "I found Liverpool Talking Newspaper near Liverpool" in speech


def test_single_source_without_a_named_city_omits_proximity_claim():
    assert AvailabilitySpeech.one_local_source("York Talking News") == (
        "I found York Talking News. Would you like to listen?"
    )


@pytest.mark.asyncio
async def test_resolver_location_payload_routes_to_availability_instead_of_search(
    mock_handler_input,
):
    handler_input = AvailabilityTestSupport.intent(
        mock_handler_input,
        "PlayLocalIntent",
        {"localQuery": {"name": "localQuery", "value": "Swindon"}},
    )
    handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "userCity": "Swindon",
        "latitude": 51.56,
        "longitude": -1.78,
    }
    deps = AvailabilityTestSupport.dependencies(
        {
            "failed": False,
            "page": 0,
            "total_pages": 1,
            "has_more": False,
            "organizations": [
                {"type": "organization", "id": "org-1", "name": "Talking News Federation"}
            ],
            "creators": [],
        }
    )
    nlp = {
        "intent": "local",
        "directDiscoveryRequest": True,
        "searchPayload": {
            "query": "",
            "filter": {},
            "sort": "latest",
            "page": 0,
            "limit": 5,
        },
        "slots": {"residualQuery": "", "isLocal": True, "sort": "latest"},
    }

    response = await Availability(deps=deps).begin_local(handler_input, nlp)

    deps.heara.availability.assert_awaited_once()
    deps.heara.search.assert_not_awaited()
    assert deps.heara.availability.await_args.args[0]["filter"] == {
        "location": {
            "city": "Swindon",
            "latitude": 51.56,
            "longitude": -1.78,
        }
    }
    speech = AvailabilityTestSupport.speech(response)
    assert "I found Talking News Federation." in speech
    assert "near Swindon" not in speech
    assert "Would you like to listen?" in speech
    assert "I found one local source" not in speech
    assert DialogStateManager.get_active(handler_input)["type"] == "availability"


@pytest.mark.asyncio
async def test_source_with_publications_and_tracks_asks_for_content_type(mock_handler_input):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, "AMAZON.YesIntent")
    deps = AvailabilityTestSupport.dependencies(
        {
            "failed": False,
            "page": 0,
            "total_pages": 1,
            "has_more": False,
            "publication_count": 4,
            "standalone_track_count": 7,
            "publications": [
                {
                    "type": "publication",
                    "id": "publication-1",
                    "name": "Redcar News",
                    "trackCount": 3,
                }
            ],
        }
    )

    response = await Availability(deps=deps)._begin_source(
        handler_input,
        {"type": "organization", "id": "org-1", "name": "Redcar Talking Newspaper"},
        {"query": "", "filter": {"organizationIds": ["org-1"]}},
    )

    speech = AvailabilityTestSupport.speech(response)
    assert "Redcar Talking Newspaper has four publications and seven tracks" in speech
    assert "Would you like to hear a publication, or choose a track?" in speech
    active = DialogStateManager.get_active(handler_input)
    assert active["context"]["kind"] == "format"
    assert response["shouldEndSession"] is False


@pytest.mark.asyncio
async def test_source_with_only_publications_lists_three_at_a_time(mock_handler_input):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, "AMAZON.YesIntent")
    publications = [
        {
            "type": "publication",
            "id": f"publication-{index}",
            "name": f"Redcar News {index}",
            "trackCount": 3,
        }
        for index in range(1, 4)
    ]
    deps = AvailabilityTestSupport.dependencies(
        {
            "failed": False,
            "page": 0,
            "total_pages": 2,
            "has_more": True,
            "publication_count": 4,
            "standalone_track_count": 0,
            "publications": publications,
        }
    )

    response = await Availability(deps=deps)._begin_source(
        handler_input,
        {"type": "organization", "id": "org-1", "name": "Redcar Talking Newspaper"},
        {"query": "", "filter": {"organizationIds": ["org-1"]}},
    )

    speech = AvailabilityTestSupport.speech(response)
    assert "Redcar Talking Newspaper has four publications" in speech
    assert "Here are the first three publications" in speech
    assert "First, Redcar News 1" in speech
    assert "Fourth" not in speech
    assert "first, second, third, show more, or next" in speech
    assert "something else to return to search" in speech
    assert DialogStateManager.get_active(handler_input)["context"]["kind"] == "publication"


@pytest.mark.asyncio
async def test_selecting_first_publication_speaks_publication_not_organization(
    mock_handler_input,
):
    handler_input = AvailabilityTestSupport.intent(
        mock_handler_input,
        "ClarifySelectionIntent",
        {"selection": {"name": "selection", "value": "first"}},
    )
    publication = {
        "type": "publication",
        "id": "publication-test",
        "name": "Test Pub for the seventh of September",
    }
    DialogStateManager.activate(
        handler_input,
        "availability",
        context={
            "kind": "publication",
            "source": {
                "type": "organization",
                "id": "org-tnf",
                "name": "Talking News Federation",
            },
            "candidates": [publication],
            "choiceCandidates": [publication],
            "displayedCandidates": [publication],
            "offset": 0,
        },
    )
    deps = AvailabilityTestSupport.dependencies(
        {"failed": False},
        {
            "failed": False,
            "results": [
                {
                    "contentId": "track-test",
                    "title": "Test publication track",
                    "publicationId": "publication-test",
                    "publicationTitle": "Test Pub",
                    "organizationName": "Talking News Federation",
                    "audioUrl": "https://cdn.hear.media/track-test.mp3",
                }
            ],
            "total_hits": 1,
        },
    )
    deps.playback = SimpleNamespace(
        queue=SimpleNamespace(initialize=lambda *_args, **_kwargs: None),
        start=AsyncMock(return_value={"shouldEndSession": True}),
    )
    deps.browse = SimpleNamespace(set_catalog=lambda *_args, **_kwargs: None)

    response = await Availability(deps=deps).handle_dialog(handler_input)

    assert response == {"shouldEndSession": True}
    assert deps.heara.search.await_args.args[0]["filter"] == {
        "publicationIds": ["publication-test"]
    }
    options = deps.playback.start.await_args.args
    assert options[2] == "Playing Test Pub for the seventh of September."
    assert deps.heara.search.return_value["_request_label"] == (
        "Test Pub for the seventh of September"
    )
    assert DialogStateManager.get_active(handler_input) is None


@pytest.mark.asyncio
async def test_source_without_publications_silently_searches_tracks(mock_handler_input):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, "AMAZON.YesIntent")
    playable = {
        "contentId": "track-1",
        "title": "Council Meeting Update",
        "audioUrl": "https://cdn.hear.media/track-1.mp3",
    }
    deps = AvailabilityTestSupport.dependencies(
        {
            "failed": False,
            "page": 0,
            "total_pages": 1,
            "has_more": False,
            "publication_count": 0,
            "standalone_track_count": 1,
            "publications": [],
        },
        {"failed": False, "results": [playable], "total_hits": 1, "page": 0},
    )
    deps.browse = SimpleNamespace(set_catalog=lambda *args, **kwargs: None)
    deps.playback = SimpleNamespace(
        queue=SimpleNamespace(initialize=lambda *args, **kwargs: None),
        start=AsyncMock(return_value={"shouldEndSession": True}),
    )

    response = await Availability(deps=deps)._begin_source(
        handler_input,
        {"type": "organization", "id": "org-1", "name": "Redcar Talking Newspaper"},
        {"query": "", "filter": {"organizationIds": ["org-1"]}},
    )

    search_payload = deps.heara.search.await_args.args[0]
    assert search_payload["filter"] == {
        "organizationIds": ["org-1"],
        "isPublication": False,
    }
    assert deps.heara.search.await_count == 1
    assert response == {"shouldEndSession": True}
    intro = deps.playback.start.await_args.args[2]
    assert intro == "Playing Redcar Talking Newspaper."


@pytest.mark.asyncio
async def test_availability_dialog_accepts_ordinal_and_keeps_retry_open(mock_handler_input):
    handler_input = AvailabilityTestSupport.intent(
        mock_handler_input,
        "ClarifySelectionIntent",
        {"selection": {"name": "selection", "value": "second"}},
    )
    candidates = [
        {"type": "source", "id": "one", "name": "First Source"},
        {"type": "source", "id": "two", "name": "Second Source"},
    ]
    User.update(
        handler_input,
        {
            "activeDialog": {
                "type": "availability",
                "context": {
                    "kind": "source",
                    "candidates": candidates,
                    "choiceCandidates": candidates,
                    "displayedCandidates": candidates,
                    "offset": 0,
                    "apiPage": 0,
                    "totalPages": 1,
                    "hasMore": False,
                    "baseSearchPayload": {},
                },
                "expiresAt": 4102444800,
            }
        },
    )
    deps = AvailabilityTestSupport.dependencies(
        {
            "failed": False,
            "publication_count": 4,
            "standalone_track_count": 3,
            "publications": [{"type": "publication", "id": "publication-1", "name": "Local News"}],
            "page": 0,
            "total_pages": 1,
            "has_more": False,
        }
    )

    response = await Availability(deps=deps).handle_dialog(handler_input)

    body = deps.heara.availability.await_args.args[0]
    assert body["filter"] == {"creatorId": "two"}
    assert "Second Source has four publications and three tracks" in AvailabilityTestSupport.speech(
        response
    )
    assert response["shouldEndSession"] is False


@pytest.mark.asyncio
async def test_declining_single_available_source_uses_natural_uk_english(mock_handler_input):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, "AMAZON.NoIntent")
    candidate = {"type": "organization", "id": "org-1", "name": "Local Voice"}
    User.update(
        handler_input,
        {
            "activeDialog": {
                "type": "availability",
                "context": {
                    "kind": "source",
                    "candidates": [candidate],
                    "singleChoice": True,
                },
            }
        },
    )
    deps = AvailabilityTestSupport.dependencies({"failed": False})

    response = await Availability(deps=deps).handle_dialog(handler_input)

    speech = AvailabilityTestSupport.speech(response)
    assert "What would you like to listen to instead?" in speech
    assert "What would you like to hear instead?" not in speech


@pytest.mark.asyncio
async def test_selecting_tracks_starts_playback_without_offering_track_choices(mock_handler_input):
    handler_input = AvailabilityTestSupport.intent(
        mock_handler_input,
        "ClarifySelectionIntent",
        {"selection": {"name": "selection", "value": "tracks"}},
    )
    format_candidates = [
        {"type": "format", "id": "publication", "name": "publications"},
        {"type": "format", "id": "track", "name": "tracks"},
    ]
    source = {"type": "organization", "id": "org-1", "name": "Redcar Talking Newspaper"}
    User.update(
        handler_input,
        {
            "activeDialog": {
                "type": "availability",
                "context": {
                    "kind": "format",
                    "source": source,
                    "candidates": format_candidates,
                    "choiceCandidates": format_candidates,
                    "displayedCandidates": format_candidates,
                    "publicationCandidates": [],
                    "publicationCount": 4,
                    "trackCount": 4,
                    "baseSearchPayload": {},
                    "offset": 0,
                },
                "expiresAt": 4102444800,
            }
        },
    )
    tracks = [
        {
            "contentId": f"track-{index}",
            "title": f"Local Track {index}",
            "audioUrl": f"https://cdn.hear.media/track-{index}.mp3",
        }
        for index in range(1, 5)
    ]
    deps = AvailabilityTestSupport.dependencies(
        {"failed": False},
        {"failed": False, "results": tracks[:3], "total_hits": 4, "total_pages": 2, "page": 0},
    )

    deps.playback = SimpleNamespace(
        queue=SimpleNamespace(initialize=lambda *_args, **_kwargs: None),
        start=AsyncMock(return_value={"shouldEndSession": True}),
    )
    deps.browse = SimpleNamespace(set_catalog=lambda *_args, **_kwargs: None)
    availability = Availability(deps=deps)

    response = await availability.handle_dialog(handler_input)

    assert response == {"shouldEndSession": True}
    assert deps.heara.search.await_args.args[0]["limit"] == 3
    deps.playback.start.assert_awaited_once()
    assert deps.playback.start.await_args.args[1]["contentId"] == "track-1"
    assert deps.playback.start.await_args.args[2] == "Playing Redcar Talking Newspaper."
    assert DialogStateManager.get_active(handler_input) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "slots"),
    [
        (
            "ClarifySelectionIntent",
            {"selection": {"name": "selection", "value": "tracks"}},
        ),
        (
            "SearchContentIntent",
            {"topic": {"name": "topic", "value": "tracks"}},
        ),
        (
            "PlayContentIntent",
            {"topic": {"name": "topic", "value": "tracks"}},
        ),
    ],
)
async def test_availability_track_choice_survives_alexa_intent_variants(
    mock_handler_input, intent_name, slots
):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, intent_name, slots)
    format_candidates = [
        {"type": "format", "id": "publication", "name": "publications"},
        {"type": "format", "id": "track", "name": "tracks"},
    ]
    source = {"type": "creator", "id": "creator-1", "name": "Pendle Voice Dalesman"}
    DialogStateManager.activate(
        handler_input,
        "availability",
        context={
            "kind": "format",
            "source": source,
            "candidates": format_candidates,
            "choiceCandidates": format_candidates,
            "displayedCandidates": format_candidates,
            "publicationCandidates": [],
            "publicationCount": 4,
            "trackCount": 4,
            "baseSearchPayload": {},
            "offset": 0,
        },
    )
    deps = AvailabilityTestSupport.dependencies(
        {"failed": False},
        {
            "failed": False,
            "results": [
                {
                    "contentId": "track-1",
                    "title": "Pendle Voice News",
                    "audioUrl": "https://cdn.hear.media/track-1.mp3",
                }
            ],
            "total_hits": 1,
        },
    )
    deps.playback = SimpleNamespace(
        queue=SimpleNamespace(initialize=lambda *_args, **_kwargs: None),
        start=AsyncMock(return_value={"shouldEndSession": True}),
    )
    deps.browse = SimpleNamespace(set_catalog=lambda *_args, **_kwargs: None)

    response = await Availability(deps=deps).handle_dialog(handler_input)

    assert response == {"shouldEndSession": True}
    deps.heara.search.assert_awaited_once()
    deps.playback.start.assert_awaited_once()
    assert DialogStateManager.get_active(handler_input) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "slots"),
    [
        ("PlayPublicationIntent", {}),
        (
            "ClarifySelectionIntent",
            {"selection": {"name": "selection", "value": "publications"}},
        ),
        (
            "SearchContentIntent",
            {"topic": {"name": "topic", "value": "publication"}},
        ),
    ],
)
async def test_availability_publication_choice_survives_alexa_intent_variants(
    mock_handler_input, intent_name, slots
):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, intent_name, slots)
    publication = {
        "type": "publication",
        "id": "publication-1",
        "name": "Pendle Voice Dalesman",
    }
    format_candidates = [
        {"type": "format", "id": "publication", "name": "publications"},
        {"type": "format", "id": "track", "name": "tracks"},
    ]
    source = {"type": "creator", "id": "creator-1", "name": "Pendle Voice"}
    DialogStateManager.activate(
        handler_input,
        "availability",
        context={
            "kind": "format",
            "source": source,
            "candidates": format_candidates,
            "choiceCandidates": format_candidates,
            "displayedCandidates": format_candidates,
            "publicationCandidates": [publication],
            "publicationCount": 1,
            "trackCount": 4,
            "baseSearchPayload": {},
            "offset": 0,
        },
    )
    deps = AvailabilityTestSupport.dependencies(
        {"failed": False},
        {
            "failed": False,
            "results": [
                {
                    "contentId": "track-1",
                    "title": "Pendle Voice Dalesman",
                    "audioUrl": "https://cdn.hear.media/track-1.mp3",
                }
            ],
            "total_hits": 1,
        },
    )
    deps.playback = SimpleNamespace(
        queue=SimpleNamespace(initialize=lambda *_args, **_kwargs: None),
        start=AsyncMock(return_value={"shouldEndSession": True}),
    )
    deps.browse = SimpleNamespace(set_catalog=lambda *_args, **_kwargs: None)

    response = await Availability(deps=deps).handle_dialog(handler_input)

    assert response == {"shouldEndSession": True}
    sent = deps.heara.search.await_args.args[0]
    assert sent["filter"] == {"publicationIds": ["publication-1"]}
    deps.playback.start.assert_awaited_once()
    assert DialogStateManager.get_active(handler_input) is None


@pytest.mark.asyncio
async def test_more_page_failure_keeps_dialog_open_for_retry(mock_handler_input):
    handler_input = AvailabilityTestSupport.intent(mock_handler_input, "ShowMoreBrowseIntent")
    candidates = [
        {"type": "organization", "id": f"org-{index}", "name": f"Local Source {index}"}
        for index in range(1, 4)
    ]
    User.update(
        handler_input,
        {
            "activeDialog": {
                "type": "availability",
                "context": {
                    "kind": "source",
                    "candidates": candidates,
                    "choiceCandidates": candidates,
                    "displayedCandidates": candidates,
                    "offset": 0,
                    "apiPage": 0,
                    "totalPages": 2,
                    "hasMore": True,
                    "availabilityFilter": {"location": {"city": "Swindon"}},
                    "baseSearchPayload": {},
                },
                "expiresAt": 4102444800,
            }
        },
    )
    deps = AvailabilityTestSupport.dependencies({"failed": True})

    response = await Availability(deps=deps).handle_dialog(handler_input)

    assert "couldn't load the next source choices just now" in AvailabilityTestSupport.speech(
        response
    )
    assert response["shouldEndSession"] is False
    assert DialogStateManager.get_active(handler_input)["type"] == "availability"
