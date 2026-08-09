from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.clients.alexa_locality import AlexaLocalityClient
from src.runtime import AttrDict


class _Pool:
    def __init__(self, response):
        self.client = SimpleNamespace(get=AsyncMock(return_value=response))

    def get(self):
        return self.client


def _handler_input(*, scopes=None):
    return SimpleNamespace(request_envelope=AttrDict({
        "context": {"System": {
            "apiEndpoint": "https://api.eu.amazonalexa.com",
            "apiAccessToken": "request-token",
            "device": {"deviceId": "device-123"},
            "user": {"permissions": {"scopes": scopes or {}}},
        }},
    }))


@pytest.mark.asyncio
async def test_address_api_is_authoritative_when_deprecated_scopes_are_absent():
    response = SimpleNamespace(
        status_code=200,
        raise_for_status=lambda: None,
        json=lambda: {
            "city": "Burnley",
            "postalCode": "BB10 1AA",
            "countryCode": "GB",
            "stateOrRegion": "Lancashire",
            "addressLine3": "",
        },
    )
    pool = _Pool(response)
    client = AlexaLocalityClient(pool=pool)

    result = await client.detect_device_location(_handler_input())

    assert result["_status"] == "resolved"
    assert result["city"] == "Burnley"
    call = pool.client.get.await_args
    assert call.args[0] == (
        "https://api.eu.amazonalexa.com/v1/devices/device-123/settings/address"
    )
    assert call.kwargs["headers"] == {
        "Authorization": "Bearer request-token",
        "Accept": "application/json",
    }


@pytest.mark.asyncio
async def test_address_api_403_is_reported_as_permission_denied():
    pool = _Pool(SimpleNamespace(status_code=403))
    result = await AlexaLocalityClient(pool=pool).detect_device_location(
        _handler_input(),
    )
    assert result == {"_status": "permission_denied"}


@pytest.mark.asyncio
async def test_address_uses_district_when_city_is_empty():
    response = SimpleNamespace(
        status_code=200,
        raise_for_status=lambda: None,
        json=lambda: {
            "city": "",
            "addressLine3": "",
            "districtOrCounty": "Pendle",
            "postalCode": "BB9 7LG",
            "countryCode": "GB",
            "stateOrRegion": "Lancashire",
        },
    )
    result = await AlexaLocalityClient(pool=_Pool(response)).detect_device_location(
        _handler_input(),
    )
    assert result["city"] == "Pendle"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(401, "unauthorized"), (404, "not_found"), (204, "empty")],
)
async def test_address_api_preserves_non_permission_failure(status_code, expected):
    pool = _Pool(SimpleNamespace(status_code=status_code))
    result = await AlexaLocalityClient(pool=pool).detect_device_location(
        _handler_input(),
    )
    assert result == {"_status": expected}
