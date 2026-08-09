from __future__ import annotations

import logging
import httpx
import pytest

from src.clients.resolver import (
    ResolvedEntity,
    ResolverClient,
    ResolverResult,
    ResolverUnavailable,
)



def _response(**overrides):
    payload = {
        "status": "resolved",
        "intent": "publication",
        "entities": [
            {
                "entityType": "creator", "entityId": "creator-1",
                "canonicalValue": "Adeshina Ayomide", "originalText": "adeshina",
                "confidence": 1, "method": "exact", "start": 23, "end": 31,
                "latitude": None, "longitude": None, "countryCode": None,
            },
            {
                "entityType": "publication", "entityId": "publication-1",
                "canonicalValue": "Buxton Talking Sport", "originalText": "sport",
                "confidence": 1, "method": "bare_match", "start": 12, "end": 17,
                "latitude": None, "longitude": None, "countryCode": None,
            },
            {
                "entityType": "category", "entityId": "sport",
                "canonicalValue": "Sport", "originalText": "sport",
                "confidence": 1, "method": "bare_match", "start": 12, "end": 17,
                "latitude": None, "longitude": None, "countryCode": None,
            },
            {
                "entityType": "tag", "entityId": "sport",
                "canonicalValue": "#sport", "originalText": "sport",
                "confidence": 1, "method": "bare_match", "start": 12, "end": 17,
                "latitude": None, "longitude": None, "countryCode": None,
            },
        ],
        "slots": {
            "residualQuery": "", "latest": True, "isRecommended": False,
            "isPublication": False, "sort": "latest",
            "publishedFrom": None, "publishedTo": None,
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
        host="https://resolver.hear.media/", api_key="secret",
        default_country="gb", timeout_ms=1500,
        transport=httpx.MockTransport(handler),
    )
    with caplog.at_level(logging.INFO, logger="src.clients.resolver"):
        result = await client.resolve(
            "latest sport by adeshina", alexa_user_id="amzn-user", timezone="Europe/London",
        )

    request = captured["request"]
    assert str(request.url) == "https://resolver.hear.media/resolve"
    assert request.headers["x-api-key"] == "secret"
    assert request.read() == (
        b'{"utterance":"latest sport by adeshina","timezone":"Europe/London",'
        b'"country_code":"gb","alexaUserId":"amzn-user"}'
    )
    assert isinstance(result, ResolverResult)
    assert '"utterance":"latest sport by adeshina"' in caplog.text
    assert '"alexaUserId":"<present>"' in caplog.text
    assert "resolver response httpStatus=200" in caplog.text
    assert '"intent":"publication"' in caplog.text
    assert '"timingMs":12.464' in caplog.text
    assert '"latitude"' not in caplog.text
    assert '"longitude"' not in caplog.text
    assert "amzn-user" not in caplog.text
    assert "secret" not in caplog.text


def test_canonical_entities_drive_all_discovered_facets_without_fake_ambiguity():
    result = ResolverResult.from_payload(_response()).to_alexa_payload()

    assert result["slots"]["creatorIds"] == ["creator-1"]
    assert result["slots"]["creatorName"] == "Adeshina Ayomide"
    assert result["slots"]["publicationIds"] == ["publication-1"]
    assert result["slots"]["publicationName"] == "Buxton Talking Sport"
    assert result["slots"]["category"] == "sport"
    assert result["slots"]["categoryName"] == "Sport"
    assert result["slots"]["tags"] == ["sport"]
    assert result["slots"]["tagNames"] == ["#sport"]
    assert result["slots"]["ambiguousReferences"] == []
    assert result["ambiguities"] == []


def test_explicit_publication_uses_id_without_generic_publication_filter():
    payload = _response()
    payload["entities"] = [payload["entities"][1]]
    result = ResolverResult.from_payload(payload).to_alexa_payload()

    assert result["slots"]["publicationIds"] == ["publication-1"]
    assert result["slots"]["publicationName"] == "Buxton Talking Sport"
    assert result["slots"]["isPublication"] is False
    assert result["slots"]["searchPlan"]["filter"] == {
        "publicationIds": ["publication-1"],
    }


def test_resolver_search_plan_normalizes_null_query_and_unsupported_sort():
    payload = _response()
    payload["slots"].update({"residualQuery": None, "sort": "relevance"})

    result = ResolverResult.from_payload(payload).to_alexa_payload()

    assert result["searchPayload"]["query"] == ""
    assert "sort" not in result["searchPayload"]
    assert result["slots"]["searchPlan"] == result["searchPayload"]


def test_overlapping_source_and_location_does_not_overconstrain_search():
    payload = _response(intent="creator")
    payload["entities"] = [{
        "entityType": "creator",
        "entityId": "creator-wakefield",
        "canonicalValue": "Wakefield Talking Newspaper",
        "originalText": "Wakefield",
        "confidence": 1,
        "method": "bare_match",
        "start": 0,
        "end": 9,
        "latitude": None,
        "longitude": None,
        "countryCode": None,
    }, {
        "entityType": "location",
        "entityId": "wakefield",
        "canonicalValue": "Wakefield",
        "originalText": "Wakefield",
        "confidence": 1,
        "method": "exact",
        "start": 0,
        "end": 9,
        "latitude": 53.6825,
        "longitude": -1.4975,
        "countryCode": "gb",
    }]
    payload["slots"].update({
        "city": "Wakefield",
        "placeName": "Wakefield",
        "countryCode": "gb",
        "latitude": 53.6825,
        "longitude": -1.4975,
        "isLocal": True,
    })

    result = ResolverResult.from_payload(payload).to_alexa_payload()

    assert result["searchPayload"]["filter"] == {
        "creatorIds": ["creator-wakefield"],
    }
    assert result["resolution"]["match"] is None
    assert "city" not in result["slots"]
    assert "isLocal" not in result["slots"]


def test_location_context_keeps_overlapping_town_for_onboarding():
    payload = _response(intent="creator")
    payload["entities"] = [{
        "entityType": "creator",
        "entityId": "creator-gloucester",
        "canonicalValue": "Gloucester Talking Newspaper",
        "originalText": "gloucester",
        "confidence": 1,
        "method": "bare_match",
        "start": 0,
        "end": 10,
        "latitude": None,
        "longitude": None,
        "countryCode": None,
    }, {
        "entityType": "location",
        "entityId": "location-gloucester",
        "canonicalValue": "Gloucester",
        "originalText": "gloucester",
        "confidence": 1,
        "method": "bare_match",
        "start": 0,
        "end": 10,
        "latitude": 51.8653,
        "longitude": -2.2458,
        "countryCode": "gb",
    }]

    result = ResolverResult.from_payload(payload).to_alexa_payload(
        prefer_location=True,
    )

    assert result["resolution"]["match"] == {
        "city": "Gloucester",
        "locality": "Gloucester",
        "countryCode": "gb",
        "latitude": 51.8653,
        "longitude": -2.2458,
        "confidence": 1.0,
        "method": "bare_match",
    }
    assert result["slots"]["city"] == "Gloucester"


def test_resolver_ambiguities_are_normalized_and_exposed_to_alexa():
    payload = _response(intent="search")
    payload["entities"] = []
    payload["ambiguities"] = [{
        "phrase": "pendle voice",
        "candidates": [{
            "entityType": "creator",
            "entityId": "creator-leader",
            "canonicalValue": "Pendle Voice Leader and Times",
        }, {
            "entityType": "creator",
            "entityId": "creator-dalesman",
            "canonicalValue": "Pendle Voice Dalesman",
        }, {
            "entityType": "organization",
            "entityId": "org-leader",
            "canonicalValue": "Pendle Voice Leader and Times",
        }],
    }]

    result = ResolverResult.from_payload(payload).to_alexa_payload()

    expected = [{
        "phrase": "pendle voice",
        "candidates": [{
            "type": "creator",
            "id": "creator-leader",
            "name": "Pendle Voice Leader and Times",
        }, {
            "type": "creator",
            "id": "creator-dalesman",
            "name": "Pendle Voice Dalesman",
        }, {
            "type": "organization",
            "id": "org-leader",
            "name": "Pendle Voice Leader and Times",
        }],
    }]
    assert result["ambiguities"] == expected
    assert result["slots"]["ambiguousReferences"] == expected


def test_client_defaults_use_fixed_service_contract_without_resolver_settings():
    client = ResolverClient(api_key="secret")

    assert client._host == "https://resolver.hear.media"
    assert client._default_country == "gb"
    assert client._timeout.connect == 5.0


def test_multiple_entities_of_one_type_remain_distinct_discoveries():
    payload = _response(intent="creator")
    payload["entities"] = [payload["entities"][0], {
        **payload["entities"][0],
        "entityId": "creator-2", "canonicalValue": "Another Creator",
    }]
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
        host="https://resolver.test", api_key="secret",
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json={})),
    )
    with pytest.raises(ResolverUnavailable):
        await client.resolve("sport")


@pytest.mark.asyncio
async def test_client_rejects_malformed_success_response():
    client = ResolverClient(
        host="https://resolver.test", api_key="secret",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"status": "resolved"})),
    )
    with pytest.raises(ResolverUnavailable):
        await client.resolve("sport")


@pytest.mark.asyncio
async def test_client_converts_network_failure_to_unavailable():
    def fail(request):
        raise httpx.ConnectError("offline", request=request)

    client = ResolverClient(
        host="https://resolver.test", api_key="secret",
        transport=httpx.MockTransport(fail),
    )
    with pytest.raises(ResolverUnavailable):
        await client.resolve("sport")
