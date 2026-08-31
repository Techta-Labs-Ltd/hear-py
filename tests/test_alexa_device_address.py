from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import config.permission_scopes as permission_scopes
from src.alexa.runtime import AttrDict
from src.clients.alexa_settings import AlexaSettingsClient
from src.services.alexa_locality import AlexaLocalityService


class _Pool:
    def __init__(self, response):
        self.client = SimpleNamespace(get=AsyncMock(return_value=response))

    def get(self):
        return self.client


def _handler_input(*, scopes=None):
    return SimpleNamespace(
        request_envelope=AttrDict(
            {
                "context": {
                    "System": {
                        "apiEndpoint": "https://api.eu.amazonalexa.com",
                        "apiAccessToken": "request-token",
                        "device": {"deviceId": "device-123"},
                        "user": {"permissions": {"scopes": scopes or {}}},
                    }
                }
            }
        )
    )


@pytest.mark.asyncio
async def test_address_api_is_used_only_with_full_address_permission(caplog):
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
    client = AlexaLocalityService(AlexaSettingsClient(pool=pool))
    with caplog.at_level(logging.INFO, logger="src.clients.alexa_settings"):
        result = await client.detect_device_location(
            _handler_input(
                scopes={permission_scopes.DEVICE_ADDRESS: {"status": "GRANTED"}}
            )
        )
    assert result["_status"] == "resolved"
    assert result["city"] == "Burnley"
    call = pool.client.get.await_args
    assert call.args[0] == "https://api.eu.amazonalexa.com/v1/devices/device-123/settings/address"
    assert call.kwargs["headers"] == {
        "Authorization": "Bearer request-token",
        "Accept": "application/json",
    }
    assert "path=/v1/devices/<redacted>/settings/address" in caplog.text
    assert "deviceIdPresent=true" in caplog.text
    assert '"city":"Burnley"' in caplog.text
    assert '"stateOrRegion":"Lancashire"' in caplog.text
    assert '"postalCodePresent":true' in caplog.text
    assert "device-123" not in caplog.text
    assert "request-token" not in caplog.text
    assert "BB10 1AA" not in caplog.text


@pytest.mark.asyncio
async def test_address_api_403_is_reported_as_permission_denied():
    pool = _Pool(SimpleNamespace(status_code=403))
    result = await AlexaLocalityService(AlexaSettingsClient(pool=pool)).detect_device_location(
        _handler_input()
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
    result = await AlexaLocalityService(
        AlexaSettingsClient(pool=_Pool(response))
    ).detect_device_location(
        _handler_input(scopes={permission_scopes.DEVICE_ADDRESS: {"status": "GRANTED"}})
    )
    assert result["city"] == "Pendle"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(401, "unauthorized"), (404, "not_found"), (204, "empty")],
)
async def test_address_api_preserves_non_permission_failure(status_code, expected):
    pool = _Pool(SimpleNamespace(status_code=status_code))
    result = await AlexaLocalityService(AlexaSettingsClient(pool=pool)).detect_device_location(
        _handler_input(scopes={permission_scopes.DEVICE_ADDRESS: {"status": "GRANTED"}})
    )
    assert result == {"_status": expected}


@pytest.mark.asyncio
async def test_address_api_is_not_called_without_permission():
    pool = _Pool(SimpleNamespace(status_code=200))
    result = await AlexaLocalityService(AlexaSettingsClient(pool=pool)).detect_device_location(
        _handler_input()
    )
    assert result == {"_status": "permission_denied"}
    pool.client.get.assert_not_awaited()
