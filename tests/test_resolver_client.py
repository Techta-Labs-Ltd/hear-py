from __future__ import annotations

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
async def test_client_sends_documented_request_and_api_key():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=_response())

    client = ResolverClient(
        host="https://resolver.hear.media/", api_key="secret",
        default_country="gb", timeout_ms=1500,
        transport=httpx.MockTransport(handler),
    )
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
