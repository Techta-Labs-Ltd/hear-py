from __future__ import annotations

import logging

import httpx
import pytest

from src.clients.resolver import ResolverClient, ResolverOptions
from src.models.resolver import ResolvedEntity, ResolverResult, ResolverUnavailable


def _response(**overrides):
    payload = {
        "status": "resolved",
        "intent": "publication",
        "entities": [
            {
                "entityType": "creator",
                "entityId": "creator-1",
                "canonicalValue": "Adeshina Ayomide",
                "originalText": "adeshina",
                "confidence": 100,
                "method": "exact",
                "start": 23,
                "end": 31,
                "latitude": None,
                "longitude": None,
                "countryCode": None,
            },
            {
                "entityType": "publication",
                "entityId": "publication-1",
                "canonicalValue": "Buxton Talking Sport",
                "originalText": "sport",
                "confidence": 100,
                "method": "bare_match",
                "start": 12,
                "end": 17,
                "latitude": None,
                "longitude": None,
                "countryCode": None,
            },
            {
                "entityType": "category",
                "entityId": "sport",
                "canonicalValue": "Sport",
                "originalText": "sport",
                "confidence": 100,
                "method": "bare_match",
                "start": 12,
                "end": 17,
                "latitude": None,
                "longitude": None,
                "countryCode": None,
            },
            {
                "entityType": "tag",
                "entityId": "sport",
                "canonicalValue": "#sport",
                "originalText": "sport",
                "confidence": 100,
                "method": "bare_match",
                "start": 12,
                "end": 17,
                "latitude": None,
                "longitude": None,
                "countryCode": None,
            },
        ],
        "slots": {
            "residualQuery": "",
            "latest": True,
            "isRecommended": False,
            "isPublication": False,
            "sort": "latest",
            "publishedFrom": None,
            "publishedTo": None,
        },
        "ambiguities": [],
        "timingMs": 12.464,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_client_sends_documented_request_and_api_key(caplog):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=_response())

    client = ResolverClient(
        ResolverOptions(
            host="https://resolver.hear.media/",
            api_key="secret",
            default_country="gb",
            timeout_ms=1500,
            transport=httpx.MockTransport(handler),
        )
    )
    with caplog.at_level(logging.INFO, logger="src.clients.resolver"):
        result = await client.resolve(
            "latest sport by adeshina",
            alexa_user_id="amzn-user",
            listener_id="listener-1",
            timezone="Europe/London",
        )
    request = captured["request"]
    assert str(request.url) == "https://resolver.hear.media/resolve"
    assert request.headers["x-api-key"] == "secret"
    assert (
        request.read()
        == b'{"utterance":"latest sport by adeshina","timezone":"Europe/London","country_code":"gb","alexaUserId":"amzn-user","listenerId":"listener-1"}'
    )
    assert isinstance(result, ResolverResult)
    assert '"utterance":"latest sport by adeshina"' in caplog.text
    assert '"alexaUserId":"<present>"' in caplog.text
    assert '"listenerId":"<present>"' in caplog.text
    assert "resolver response httpStatus=200" in caplog.text
    assert '"intent":"publication"' in caplog.text
    assert '"timingMs":12.464' in caplog.text
    assert '"latitude"' not in caplog.text
    assert '"longitude"' not in caplog.text
    assert "amzn-user" not in caplog.text
    assert "listener-1" not in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.asyncio
async def test_anonymous_resolver_requests_use_the_bounded_warm_cache():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_response())

    client = ResolverClient(
        ResolverOptions(
            host="https://resolver.hear.media",
            api_key="secret",
            transport=httpx.MockTransport(handler),
        )
    )
    first = await client.resolve("latest sport")
    second = await client.resolve(" latest sport ")
    assert first is second
    assert calls == 1


def test_canonical_entities_drive_all_discovered_facets_without_fake_ambiguity():
    result = ResolverResult.from_payload(_response()).to_alexa_payload()
    assert result["slots"]["creatorIds"] == ["creator-1"]
    assert result["slots"]["creatorName"] == "Adeshina Ayomide"
    assert result["slots"]["publicationIds"] == ["publication-1"]
    assert result["slots"]["publicationName"] == "Buxton Talking Sport"
    assert result["slots"]["category"] == "sport"
    assert result["slots"]["categoryName"] == "Sport"
    assert result["slots"]["categorySlugs"] == ["sport"]
    assert "tags" not in result["slots"]
    assert result["slots"]["ambiguousReferences"] == []
    assert result["ambiguities"] == []


def test_all_full_confidence_categories_are_passed_directly_to_filter():
    payload = _response(intent="category")
    payload["entities"] = [
        {
            "entityType": "category",
            "entityId": slug,
            "canonicalValue": name,
            "originalText": name.lower(),
            "confidence": 100,
            "method": "bare_match",
            "start": start,
            "end": start + len(name),
            "latitude": None,
            "longitude": None,
            "countryCode": None,
        }
        for slug, name, start in (
            ("history", "History", 5),
            ("politics", "Politics", 13),
        )
    ]
    result = ResolverResult.from_payload(payload).to_alexa_payload()
    assert result["slots"]["categorySlugs"] == ["history", "politics"]
    assert result["searchPayload"]["filter"] == {"categorySlugs": ["history", "politics"]}


def test_two_full_confidence_tags_are_filtered_when_no_category_matches():
    payload = _response(intent="search")
    payload["entities"] = [
        {
            "entityType": "tag",
            "entityId": slug,
            "canonicalValue": name,
            "originalText": name,
            "confidence": 100,
            "method": "exact",
            "start": start,
            "end": start + len(name),
            "latitude": None,
            "longitude": None,
            "countryCode": None,
        }
        for slug, name, start in (
            ("local-history", "local history", 5),
            ("oral-history", "oral history", 19),
        )
    ]
    result = ResolverResult.from_payload(payload).to_alexa_payload()
    assert result["slots"]["tags"] == ["local-history", "oral-history"]
    assert result["searchPayload"]["filter"] == {"tags": ["local-history", "oral-history"]}


def test_single_or_partial_tag_is_not_used_as_a_filter():
    payload = _response(intent="search")
    payload["entities"] = [
        {
            "entityType": "tag",
            "entityId": "history",
            "canonicalValue": "History",
            "originalText": "history",
            "confidence": 80,
            "method": "fuzzy",
            "start": 5,
            "end": 12,
            "latitude": None,
            "longitude": None,
            "countryCode": None,
        }
    ]
    result = ResolverResult.from_payload(payload).to_alexa_payload()
    assert "tags" not in result["slots"]
    assert result["searchPayload"]["filter"] == {}


def test_new_integer_confidence_contract_discards_partial_phonetic_location():
    payload = _response(intent="category")
    payload["entities"] = [
        {
            "entityType": "category",
            "entityId": "sports",
            "canonicalValue": "Sports",
            "originalText": "sports",
            "confidence": 100,
            "method": "bare_match",
            "start": 12,
            "end": 18,
            "latitude": None,
            "longitude": None,
            "countryCode": None,
            "locationRole": None,
        },
        {
            "entityType": "location",
            "entityId": "location-1826486249",
            "canonicalValue": "Upwood",
            "originalText": "update",
            "confidence": 93,
            "method": "phonetic_bare",
            "start": 28,
            "end": 34,
            "latitude": 52.43,
            "longitude": -0.15,
            "countryCode": "gb",
            "locationRole": "unspecified",
        },
    ]
    payload["slots"].update(
        {
            "residualQuery": "breifing",
            "city": "Upwood",
            "latitude": 52.43,
            "longitude": -0.15,
            "isLocal": True,
        }
    )
    result = ResolverResult.from_payload(payload).to_alexa_payload()
    assert result["entities"] == [
        {
            "entityType": "category",
            "entityId": "sports",
            "canonicalValue": "Sports",
            "originalText": "sports",
            "confidence": 100,
            "method": "bare_match",
            "start": 12,
            "end": 18,
            "latitude": None,
            "longitude": None,
            "countryCode": None,
            "locationRole": None,
        }
    ]
    assert result["searchPayload"] == {
        "query": "breifing",
        "sort": "latest",
        "filter": {"categorySlugs": ["sports"]},
    }
    assert result["resolution"]["match"] is None
    assert "city" not in result["slots"]
    assert "isLocal" not in result["slots"]


def test_category_intent_discards_location_even_at_full_confidence():
    payload = _response(intent="category")
    payload["entities"] = [
        {
            "entityType": "category",
            "entityId": "sport",
            "canonicalValue": "Sport",
            "originalText": "sport",
            "confidence": 100,
            "method": "bare_match",
            "start": 12,
            "end": 17,
            "latitude": None,
            "longitude": None,
            "countryCode": None,
            "locationRole": None,
        },
        {
            "entityType": "location",
            "entityId": "location-upwood",
            "canonicalValue": "Upwood",
            "originalText": "update",
            "confidence": 100,
            "method": "phonetic_bare",
            "start": 27,
            "end": 33,
            "latitude": 52.43,
            "longitude": -0.15,
            "countryCode": "gb",
            "locationRole": "unspecified",
        },
    ]
    payload["slots"].update(
        {
            "residualQuery": "breifing",
            "city": "Upwood",
            "countryCode": "gb",
            "latitude": 52.43,
            "longitude": -0.15,
            "isLocal": True,
        }
    )
    result = ResolverResult.from_payload(payload).to_alexa_payload()
    assert [entity["entityType"] for entity in result["entities"]] == ["category"]
    assert result["searchPayload"]["filter"] == {"categorySlugs": ["sport"]}
    assert result["resolution"]["match"] is None
    for key in ("city", "placeName", "countryCode", "latitude", "longitude", "isLocal"):
        assert key not in result["slots"]


@pytest.mark.parametrize("confidence", [0, 101, 1.0, 99.5, "100", True])
def test_entity_model_rejects_confidence_outside_integer_1_to_100(confidence):
    entity = {**_response()["entities"][0], "confidence": confidence}
    with pytest.raises(ResolverUnavailable):
        ResolvedEntity.from_payload(entity)


def test_explicit_publication_uses_id_without_generic_publication_filter():
    payload = _response()
    payload["entities"] = [payload["entities"][1]]
    result = ResolverResult.from_payload(payload).to_alexa_payload()
    assert result["slots"]["publicationIds"] == ["publication-1"]
    assert result["slots"]["publicationName"] == "Buxton Talking Sport"
    assert result["slots"]["isPublication"] is False
    assert result["slots"]["searchPlan"]["filter"] == {"publicationIds": ["publication-1"]}


def test_resolved_fuzzy_publication_is_preserved_as_an_explicit_source():
    payload = _response(intent="publication")
    payload["entities"] = [
        {
            **payload["entities"][1],
            "entityId": "7c5685a7-7ea6-47c3-8cfd-266cc65a43f6",
            "canonicalValue": "Lover Notation",
            "originalText": "lovers notati",
            "confidence": 89,
            "method": "fuzzy_bare",
        }
    ]

    result = ResolverResult.from_payload(payload).to_alexa_payload()

    assert result["slots"]["publicationIds"] == [
        "7c5685a7-7ea6-47c3-8cfd-266cc65a43f6"
    ]
    assert result["slots"]["publicationName"] == "Lover Notation"
    assert result["searchPayload"]["filter"] == {
        "publicationIds": ["7c5685a7-7ea6-47c3-8cfd-266cc65a43f6"]
    }
    assert result["entities"][0]["confidence"] == 89


def test_partial_source_is_not_trusted_when_resolver_intent_does_not_select_it():
    payload = _response(intent="search")
    payload["entities"] = [
        {
            **payload["entities"][1],
            "confidence": 89,
            "method": "fuzzy_bare",
        }
    ]

    result = ResolverResult.from_payload(payload).to_alexa_payload()

    assert "publicationIds" not in result["slots"]
    assert result["searchPayload"]["filter"] == {}


def test_single_exact_tag_is_used_as_a_search_filter():
    payload = _response(intent="search")
    payload["entities"] = [
        {
            **payload["entities"][3],
            "entityId": "empire",
            "canonicalValue": "#empire",
            "originalText": "empire",
        }
    ]

    result = ResolverResult.from_payload(payload).to_alexa_payload()

    assert result["slots"]["tags"] == ["empire"]
    assert result["searchPayload"]["filter"] == {"tags": ["empire"]}


def test_mixed_search_drops_partial_location_and_keeps_exact_tag():
    payload = _response(intent="search")
    payload["slots"].update({"residualQuery": "", "sort": "relevance"})
    payload["entities"] = [
        {
            "entityType": "location",
            "entityId": "location-1826457934",
            "canonicalValue": "Rhymney",
            "originalText": "roman",
            "confidence": 94,
            "method": "phonetic_bare",
            "start": 19,
            "end": 24,
            "latitude": 51.759,
            "longitude": -3.283,
            "countryCode": "gb",
            "locationRole": "unspecified",
        },
        {
            "entityType": "tag",
            "entityId": "empire",
            "canonicalValue": "#empire",
            "originalText": "empire",
            "confidence": 100,
            "method": "bare_match",
            "start": 25,
            "end": 31,
            "latitude": None,
            "longitude": None,
            "countryCode": None,
            "locationRole": None,
        },
    ]

    result = ResolverResult.from_payload(payload).to_alexa_payload(
        original_utterance="find me content on roman empire"
    )

    assert result["resolverIntent"] == "search"
    assert result["searchPayload"] == {
        "query": "",
        "filter": {"tags": ["empire"]},
    }
    assert [entity["entityType"] for entity in result["entities"]] == ["tag"]
    for key in ("city", "placeName", "latitude", "longitude", "isLocal"):
        assert key not in result["slots"]


def test_search_accepts_exact_source_location():
    payload = _response(intent="search")
    payload["entities"] = [
        {
            "entityType": "location",
            "entityId": "location-1826149980",
            "canonicalValue": "York",
            "originalText": "york",
            "confidence": 100,
            "method": "exact",
            "start": 29,
            "end": 33,
            "latitude": 53.96,
            "longitude": -1.08,
            "countryCode": "gb",
            "locationRole": "source",
        }
    ]

    result = ResolverResult.from_payload(payload).to_alexa_payload()

    assert result["searchPayload"]["filter"] == {
        "city": "York",
        "countryCode": "gb",
        "latitude": 53.96,
        "longitude": -1.08,
    }
    assert result["slots"]["isLocal"] is True


@pytest.mark.parametrize(
    ("utterance", "start", "end"),
    [("yuck", 0, 4), ("play yuck", 5, 9)],
)
def test_search_accepts_single_whole_query_unspecified_location(utterance, start, end):
    payload = _response(intent="search")
    payload["slots"].update(
        {"residualQuery": "", "latest": False, "sort": None}
    )
    payload["entities"] = [
        {
            "entityType": "location",
            "entityId": "location-1826149980",
            "canonicalValue": "York",
            "originalText": "yuck",
            "confidence": 98,
            "method": "phonetic_bare",
            "start": start,
            "end": end,
            "latitude": 53.96,
            "longitude": -1.08,
            "countryCode": "gb",
            "locationRole": "unspecified",
        }
    ]

    result = ResolverResult.from_payload(payload).to_alexa_payload(
        original_utterance=utterance
    )

    assert result["searchPayload"] == {
        "query": "",
        "filter": {
            "city": "York",
            "countryCode": "gb",
            "latitude": 53.96,
            "longitude": -1.08,
        },
    }
    assert result["slots"]["city"] == "York"
    assert result["slots"]["isLocal"] is True
    assert [entity["canonicalValue"] for entity in result["entities"]] == ["York"]


@pytest.mark.parametrize(("confidence", "accepted"), [(75, True), (74, False)])
def test_standalone_unspecified_location_confidence_boundary(confidence, accepted):
    payload = _response(intent="search")
    payload["slots"].update(
        {"residualQuery": "", "latest": False, "sort": None}
    )
    payload["entities"] = [
        {
            "entityType": "location",
            "entityId": "location-york",
            "canonicalValue": "York",
            "originalText": "yuck",
            "confidence": confidence,
            "method": "phonetic_bare",
            "start": 5,
            "end": 9,
            "latitude": 53.96,
            "longitude": -1.08,
            "countryCode": "gb",
            "locationRole": "unspecified",
        }
    ]

    result = ResolverResult.from_payload(payload).to_alexa_payload(
        original_utterance="play yuck"
    )

    assert bool(result["searchPayload"]["filter"]) is accepted
    assert result["slots"].get("city") == ("York" if accepted else None)


def test_search_chooses_highest_ranked_whole_query_unspecified_location():
    payload = _response(intent="search")
    payload["slots"].update(
        {"residualQuery": "", "latest": False, "sort": None}
    )
    payload["entities"] = [
        {
            "entityType": "location",
            "entityId": entity_id,
            "canonicalValue": city,
            "originalText": "yuck",
            "confidence": confidence,
            "method": "phonetic_bare",
            "start": 5,
            "end": 9,
            "latitude": latitude,
            "longitude": longitude,
            "countryCode": "gb",
            "locationRole": "unspecified",
        }
        for entity_id, city, confidence, latitude, longitude in (
            ("location-york", "York", 98, 53.96, -1.08),
            ("location-yorkshire", "Yorkshire", 90, 54.0, -1.5),
        )
    ]

    result = ResolverResult.from_payload(payload).to_alexa_payload(
        original_utterance="play yuck"
    )

    assert result["searchPayload"] == {
        "query": "",
        "filter": {
            "city": "York",
            "countryCode": "gb",
            "latitude": 53.96,
            "longitude": -1.08,
        },
    }
    assert result["resolution"]["match"]["city"] == "York"
    assert [entity["canonicalValue"] for entity in result["entities"]] == ["York"]


def test_search_prefers_phonetic_source_location_over_unspecified_noise():
    payload = _response(intent="search")
    payload["entities"] = [
        {
            "entityType": "location",
            "entityId": "location-1826527188",
            "canonicalValue": "Forfar",
            "originalText": "favour",
            "confidence": 92,
            "method": "phonetic_bare",
            "start": 8,
            "end": 14,
            "latitude": 56.6442,
            "longitude": -2.8884,
            "countryCode": "gb",
            "locationRole": "unspecified",
        },
        {
            "entityType": "location",
            "entityId": "location-1826454069",
            "canonicalValue": "Herne Bay",
            "originalText": "arn bay",
            "confidence": 89,
            "method": "phonetic",
            "start": 20,
            "end": 27,
            "latitude": 51.37,
            "longitude": 1.13,
            "countryCode": "gb",
            "locationRole": "source",
        },
    ]

    result = ResolverResult.from_payload(payload).to_alexa_payload(
        original_utterance="play a favour from arn bay"
    )

    assert result["searchPayload"] == {
        "query": "",
        "sort": "latest",
        "filter": {
            "city": "Herne Bay",
            "countryCode": "gb",
            "latitude": 51.37,
            "longitude": 1.13,
        },
    }
    assert result["slots"]["city"] == "Herne Bay"
    assert result["slots"]["isLocal"] is True
    assert [entity["canonicalValue"] for entity in result["entities"]] == ["Herne Bay"]


def test_search_rejects_low_confidence_source_location():
    payload = _response(intent="search")
    payload["slots"].update({"residualQuery": "", "sort": "relevance"})
    payload["entities"] = [
        {
            "entityType": "location",
            "entityId": "location-herne-bay",
            "canonicalValue": "Herne Bay",
            "originalText": "early bay",
            "confidence": 70,
            "method": "phonetic",
            "start": 10,
            "end": 19,
            "latitude": 51.37,
            "longitude": 1.13,
            "countryCode": "gb",
            "locationRole": "source",
        }
    ]

    result = ResolverResult.from_payload(payload).to_alexa_payload(
        original_utterance="play news from early bay"
    )

    assert result["searchPayload"] == {
        "query": "news from early bay",
        "filter": {},
    }
    assert result["entities"] == []


def test_search_does_not_choose_between_two_equally_credible_source_locations():
    payload = _response(intent="search")
    payload["slots"].update({"residualQuery": "", "sort": "relevance"})
    payload["entities"] = [
        {
            "entityType": "location",
            "entityId": f"location-{name.casefold().replace(' ', '-')}",
            "canonicalValue": name,
            "originalText": original,
            "confidence": confidence,
            "method": "phonetic",
            "start": start,
            "end": end,
            "latitude": latitude,
            "longitude": longitude,
            "countryCode": "gb",
            "locationRole": "source",
        }
        for name, original, confidence, start, end, latitude, longitude in (
            ("Herne Bay", "arn bay", 89, 10, 17, 51.37, 1.13),
            ("Cardiff", "card if", 88, 22, 29, 51.4816, -3.1791),
        )
    ]

    result = ResolverResult.from_payload(payload).to_alexa_payload(
        original_utterance="play news from arn bay or card if"
    )

    assert result["searchPayload"] == {
        "query": "news from arn bay or card if",
        "filter": {},
    }
    assert result["entities"] == []


def test_search_drops_unspecified_location_even_at_full_confidence():
    payload = _response(intent="search")
    payload["entities"] = [
        {
            "entityType": "location",
            "entityId": "location-reading",
            "canonicalValue": "Reading",
            "originalText": "reading",
            "confidence": 100,
            "method": "exact",
            "start": 5,
            "end": 12,
            "latitude": 51.456,
            "longitude": -0.971,
            "countryCode": "gb",
            "locationRole": "unspecified",
        }
    ]
    payload["slots"].update({"residualQuery": "", "sort": "relevance"})

    result = ResolverResult.from_payload(payload).to_alexa_payload(
        original_utterance="play reading skills"
    )

    assert result["searchPayload"] == {"query": "reading skills", "filter": {}}
    assert result["entities"] == []


@pytest.mark.parametrize("resolver_intent,entity_type", [("tag", "tag"), ("location", "location")])
def test_resolver_facet_intents_are_canonicalized_to_dispatchable_search(
    resolver_intent, entity_type
):
    payload = _response(intent=resolver_intent)
    payload["entities"] = [
        {
            "entityType": entity_type,
            "entityId": "empire" if entity_type == "tag" else "location-york",
            "canonicalValue": "#empire" if entity_type == "tag" else "York",
            "originalText": "empire" if entity_type == "tag" else "york",
            "confidence": 89,
            "method": "fuzzy_bare",
            "start": 5,
            "end": 11,
            "latitude": None if entity_type == "tag" else 53.96,
            "longitude": None if entity_type == "tag" else -1.08,
            "countryCode": None if entity_type == "tag" else "gb",
            "locationRole": None if entity_type == "tag" else "source",
        }
    ]

    result = ResolverResult.from_payload(payload).to_alexa_payload()

    assert result["intent"] == "search"
    assert result["resolverIntent"] == resolver_intent
    assert result["searchPayload"]["filter"]


def test_rejected_only_entity_falls_back_to_clean_original_query():
    payload = _response(intent="search")
    payload["entities"] = [
        {
            "entityType": "location",
            "entityId": "location-rhymney",
            "canonicalValue": "Rhymney",
            "originalText": "roman",
            "confidence": 94,
            "method": "phonetic_bare",
            "start": 19,
            "end": 24,
            "latitude": 51.759,
            "longitude": -3.283,
            "countryCode": "gb",
            "locationRole": "unspecified",
        }
    ]
    payload["slots"].update({"residualQuery": "", "sort": "relevance"})

    result = ResolverResult.from_payload(payload).to_alexa_payload(
        original_utterance="find me content on roman history"
    )

    assert result["searchPayload"] == {"query": "roman history", "filter": {}}
    assert result["entities"] == []


def test_latest_multiword_fallback_keeps_sort_out_of_query():
    payload = _response(intent="search")
    payload["entities"] = []
    payload["slots"].update(
        {"residualQuery": "", "latest": True, "sort": "latest"}
    )

    result = ResolverResult.from_payload(payload).to_alexa_payload(
        original_utterance="find me content on the latest sport news"
    )

    assert result["searchPayload"] == {
        "query": "sport news",
        "sort": "latest",
        "filter": {},
    }


def test_one_hundred_multiword_fallback_combinations_remain_searchable():
    topics = (
        "roman history",
        "local heritage",
        "community sport",
        "women's football",
        "public health",
        "mental wellbeing",
        "assistive technology",
        "local politics",
        "classical music",
        "railway memories",
        "oral history",
        "coastal news",
        "blind veterans",
        "gardening advice",
        "community theatre",
        "local business",
        "school news",
        "nature conservation",
        "military history",
        "council updates",
    )
    templates = (
        "play {topic}",
        "play content on {topic}",
        "find me content on {topic}",
        "give me something about {topic}",
        "I want to hear something on {topic}",
    )
    combinations = [
        (template.format(topic=topic), topic)
        for topic in topics
        for template in templates
    ]
    assert len(combinations) == 100

    for utterance, expected_query in combinations:
        payload = _response(intent="search")
        payload["entities"] = []
        payload["slots"].update({"residualQuery": "", "sort": "relevance"})

        result = ResolverResult.from_payload(payload).to_alexa_payload(
            original_utterance=utterance
        )

        assert result["searchPayload"]["query"].casefold() == expected_query.casefold()
    assert result["entities"] == []


def test_resolver_search_plan_normalizes_null_query_and_unsupported_sort():
    payload = _response()
    payload["slots"].update({"residualQuery": None, "sort": "relevance"})
    result = ResolverResult.from_payload(payload).to_alexa_payload()
    assert result["searchPayload"]["query"] == ""
    assert "sort" not in result["searchPayload"]
    assert result["slots"]["searchPlan"] == result["searchPayload"]


def test_overlapping_source_and_location_does_not_overconstrain_search():
    payload = _response(intent="creator")
    payload["entities"] = [
        {
            "entityType": "creator",
            "entityId": "creator-wakefield",
            "canonicalValue": "Wakefield Talking Newspaper",
            "originalText": "Wakefield",
            "confidence": 100,
            "method": "bare_match",
            "start": 0,
            "end": 9,
            "latitude": None,
            "longitude": None,
            "countryCode": None,
        },
        {
            "entityType": "location",
            "entityId": "wakefield",
            "canonicalValue": "Wakefield",
            "originalText": "Wakefield",
            "confidence": 100,
            "method": "exact",
            "start": 0,
            "end": 9,
            "latitude": 53.6825,
            "longitude": -1.4975,
            "countryCode": "gb",
        },
    ]
    payload["slots"].update(
        {
            "city": "Wakefield",
            "placeName": "Wakefield",
            "countryCode": "gb",
            "latitude": 53.6825,
            "longitude": -1.4975,
            "isLocal": True,
        }
    )
    result = ResolverResult.from_payload(payload).to_alexa_payload()
    assert result["searchPayload"]["filter"] == {"creatorIds": ["creator-wakefield"]}
    assert result["resolution"]["match"] is None
    assert "city" not in result["slots"]
    assert "isLocal" not in result["slots"]


def test_location_context_keeps_overlapping_town_for_onboarding():
    payload = _response(intent="creator")
    payload["entities"] = [
        {
            "entityType": "creator",
            "entityId": "creator-gloucester",
            "canonicalValue": "Gloucester Talking Newspaper",
            "originalText": "gloucester",
            "confidence": 100,
            "method": "bare_match",
            "start": 0,
            "end": 10,
            "latitude": None,
            "longitude": None,
            "countryCode": None,
        },
        {
            "entityType": "location",
            "entityId": "location-gloucester",
            "canonicalValue": "Gloucester",
            "originalText": "gloucester",
            "confidence": 100,
            "method": "bare_match",
            "start": 0,
            "end": 10,
            "latitude": 51.8653,
            "longitude": -2.2458,
            "countryCode": "gb",
        },
    ]
    result = ResolverResult.from_payload(payload).to_alexa_payload(prefer_location=True)
    assert result["resolution"]["match"] == {
        "city": "Gloucester",
        "locality": "Gloucester",
        "countryCode": "gb",
        "latitude": 51.8653,
        "longitude": -2.2458,
        "confidence": 100,
        "method": "bare_match",
    }
    assert result["slots"]["city"] == "Gloucester"


def test_resolver_ambiguities_are_normalized_and_exposed_to_alexa():
    payload = _response(intent="search")
    payload["entities"] = []
    payload["ambiguities"] = [
        {
            "phrase": "pendle voice",
            "candidates": [
                {
                    "entityType": "creator",
                    "entityId": "creator-leader",
                    "canonicalValue": "Pendle Voice Leader and Times",
                },
                {
                    "entityType": "creator",
                    "entityId": "creator-dalesman",
                    "canonicalValue": "Pendle Voice Dalesman",
                },
                {
                    "entityType": "organization",
                    "entityId": "org-leader",
                    "canonicalValue": "Pendle Voice Leader and Times",
                },
            ],
        }
    ]
    result = ResolverResult.from_payload(payload).to_alexa_payload()
    expected = [
        {
            "phrase": "pendle voice",
            "candidates": [
                {
                    "type": "creator",
                    "id": "creator-leader",
                    "name": "Pendle Voice Leader and Times",
                },
                {
                    "type": "creator",
                    "id": "creator-dalesman",
                    "name": "Pendle Voice Dalesman",
                },
                {
                    "type": "organization",
                    "id": "org-leader",
                    "name": "Pendle Voice Leader and Times",
                },
            ],
        }
    ]
    assert result["ambiguities"] == expected
    assert result["slots"]["ambiguousReferences"] == expected


def test_flat_creator_ambiguities_are_grouped_and_marked_ambiguous():
    payload = _response(intent="creator", entities=[])
    payload["ambiguities"] = [
        {
            "entityType": "creator",
            "entityId": "creator-dalesman",
            "canonicalValue": "Pendle Voice Dalesman",
        },
        {
            "entityType": "creator",
            "entityId": "creator-lancashire",
            "canonicalValue": "Pendle Voice Lancashire Life",
        },
        {
            "entityType": "organization",
            "entityId": "org-dalesman",
            "canonicalValue": "Pendle Voice Dalesman",
        },
        {
            "entityType": "organization",
            "entityId": "org-lancashire",
            "canonicalValue": "Pendle Voice Lancashire Life",
        },
    ]

    result = ResolverResult.from_payload(payload).to_alexa_payload(
        original_utterance="play pendle voice"
    )

    expected = [
        {
            "phrase": "pendle voice",
            "candidates": [
                {
                    "type": "creator",
                    "id": "creator-dalesman",
                    "name": "Pendle Voice Dalesman",
                },
                {
                    "type": "creator",
                    "id": "creator-lancashire",
                    "name": "Pendle Voice Lancashire Life",
                },
            ],
        }
    ]
    assert result["status"] == "ambiguous"
    assert result["ambiguities"] == expected
    assert result["slots"]["ambiguousReferences"] == expected


def test_client_defaults_use_fixed_service_contract_without_resolver_settings():
    client = ResolverClient(ResolverOptions(api_key="secret"))
    assert client._host == "https://resolver.hear.media"
    assert client._default_country == "gb"
    assert client._timeout.connect == 5.0


def test_multiple_entities_of_one_type_remain_distinct_discoveries():
    payload = _response(intent="creator")
    payload["entities"] = [
        payload["entities"][0],
        {
            **payload["entities"][0],
            "entityId": "creator-2",
            "canonicalValue": "Another Creator",
        },
    ]
    result = ResolverResult.from_payload(payload).to_alexa_payload()
    assert result["slots"]["creatorIds"] == ["creator-1", "creator-2"]
    assert result["slots"]["ambiguousReferences"] == []


def test_entity_model_rejects_missing_canonical_value():
    entity = _response()["entities"][0]
    entity.pop("canonicalValue")
    with pytest.raises(ResolverUnavailable):
        ResolvedEntity.from_payload(entity)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 422, 500])
async def test_client_converts_non_success_status_to_unavailable(status):
    client = ResolverClient(
        ResolverOptions(
            host="https://resolver.test",
            api_key="secret",
            transport=httpx.MockTransport(lambda request: httpx.Response(status, json={})),
        )
    )
    with pytest.raises(ResolverUnavailable):
        await client.resolve("sport")


@pytest.mark.asyncio
async def test_client_rejects_malformed_success_response():
    client = ResolverClient(
        ResolverOptions(
            host="https://resolver.test",
            api_key="secret",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"status": "resolved"})
            ),
        )
    )
    with pytest.raises(ResolverUnavailable):
        await client.resolve("sport")


@pytest.mark.asyncio
async def test_client_converts_network_failure_to_unavailable():

    def fail(request):
        raise httpx.ConnectError("offline", request=request)

    client = ResolverClient(
        ResolverOptions(
            host="https://resolver.test",
            api_key="secret",
            transport=httpx.MockTransport(fail),
        )
    )
    with pytest.raises(ResolverUnavailable):
        await client.resolve("sport")
