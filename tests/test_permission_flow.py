from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.alexa.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.models.permission import Permission, PermissionConstants, PermissionPolicy
from src.models.user import User
from src.services.listener_sync import ListenerSyncSupport


def _handler_input(*, token: str = "", status: str = "") -> HandlerInput:
    envelope = AttrDict(
        {
            "context": {
                "System": {
                    "apiEndpoint": "https://api.amazonalexa.com",
                    "apiAccessToken": "token",
                    "device": {"deviceId": "device"},
                    "user": {"userId": "user", "permissions": {"scopes": {}}},
                }
            },
            "request": {
                "type": "SessionResumedRequest",
                "locale": "en-GB",
                "cause": {
                    "type": "ConnectionCompleted",
                    "token": token,
                    "status": {"code": "200", "message": "OK"},
                    "result": {"status": status},
                },
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {"_store": None, "_dirty": False}
    return HandlerInput(envelope, attributes, None, ResponseBuilder())


def _deps(*, profile=None):
    user = User()
    return SimpleNamespace(
        user=user,
        onboarding=SimpleNamespace(decline_permission=MagicMock()),
        listener_profile=SimpleNamespace(
            apply_listener_profile=AsyncMock(
                return_value=profile or user.snapshot(_handler_input())
            )
        ),
        listener_sync=SimpleNamespace(sync_for_launch=AsyncMock(return_value=True)),
    )


def test_location_consent_directive_is_voice_forward_and_explains_value():
    handler_input = _handler_input()
    deps = _deps()
    response = Permission(deps=deps).start_location(handler_input)
    directive = response["directives"][0]
    assert "nearby news, sport, publications, and talking newspapers" in response[
        "outputSpeech"
    ]["ssml"]
    assert directive["type"] == "Connections.StartConnection"
    assert directive["uri"] == PermissionConstants.CONNECTION_URI
    assert directive["token"] == PermissionConstants.LOCATION_PURPOSE
    assert len(directive["input"]["permissionScopes"]) == 2
    assert "shouldEndSession" not in response


@pytest.mark.asyncio
async def test_denied_location_consent_explains_denial_and_voice_fallback():
    handler_input = _handler_input(
        token=PermissionConstants.LOCATION_PURPOSE,
        status="DENIED",
    )
    deps = _deps()
    response = await Permission(deps=deps).resume(handler_input)
    speech = response["outputSpeech"]["ssml"]
    assert "permission is currently turned off" in speech
    assert "say the name of your city" in speech
    deps.onboarding.decline_permission.assert_called_once_with(handler_input)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "expected_type"),
    [
        ({"fullName": "Ada Lovelace", "userEmail": "ada@example.com"}, "registered"),
        ({"fullName": "Ada Lovelace", "userEmail": None}, "guest"),
    ],
)
async def test_profile_consent_requires_both_name_and_email(profile, expected_type):
    handler_input = _handler_input(
        token=PermissionConstants.PROFILE_PURPOSE,
        status="ACCEPTED",
    )
    deps = _deps(profile=profile)
    await Permission(deps=deps).resume(handler_input)
    assert deps.user.snapshot(handler_input)["listenerType"] == expected_type
    deps.listener_sync.sync_for_launch.assert_awaited_once_with(handler_input)


def test_guest_sync_excludes_protected_profile_and_location_fields():
    handler_input = _handler_input()
    store = User.snapshot(handler_input)
    store.update(
        {
            "userCity": "Manchester",
            "fullName": "Hidden Name",
            "userEmail": None,
            "devicePostalCode": "M1 1AA",
            "latitude": 53.48,
            "longitude": -2.24,
        }
    )
    payload = ListenerSyncSupport.build_listener_sync_profile(handler_input, store)
    assert payload["listenerType"] == "guest"
    assert not {
        "userName",
        "userEmail",
        "city",
        "postalCode",
        "latitude",
        "longitude",
        "locality",
    }.intersection(payload)


def test_environment_specific_permission_guidance(monkeypatch):
    monkeypatch.setattr("src.models.permission.settings.STAGE", "production")
    assert "Hear service" in PermissionPolicy.app_guidance()
    monkeypatch.setattr("src.models.permission.settings.STAGE", "development")
    assert "test development" in PermissionPolicy.app_guidance()
