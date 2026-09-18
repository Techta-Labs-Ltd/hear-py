from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import config.permission_scopes as permission_scopes
from src.alexa.permission import Permission
from src.alexa.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.models.listener import IdentityContext, PrincipalType
from src.models.permission_policy import PermissionPolicy
from src.models.user import User
from src.services.listener_repository import Listener
from src.services.listener_sync import ListenerSyncPayload


def _handler_input(
    *,
    token: str = "",
    status: str = "",
    connection_code: str = "200",
    connection_message: str = "OK",
) -> HandlerInput:
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
                    "status": {
                        "code": connection_code,
                        "message": connection_message,
                    },
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
        onboarding=SimpleNamespace(
            decline_permission=MagicMock(),
            complete_location=MagicMock(),
            begin_town_capture=MagicMock(),
            complete_without_location=MagicMock(),
        ),
        listener_profile=SimpleNamespace(
            apply_listener_profile=AsyncMock(
                return_value=profile or user.snapshot(_handler_input())
            )
        ),
        listener_sync=SimpleNamespace(sync_for_launch=AsyncMock(return_value=True)),
        notifications=SimpleNamespace(enable_after_permission=MagicMock()),
        progressive=SimpleNamespace(send=AsyncMock(return_value=True)),
        locality=SimpleNamespace(detect_device_location=AsyncMock(return_value=None)),
        resolver=SimpleNamespace(resolve_utterance=AsyncMock()),
    )


def _permission(deps):
    return Permission(
        deps.user,
        deps.onboarding,
        deps.listener_profile,
        deps.listener_sync,
        deps.notifications.enable_after_permission,
        deps.progressive,
        deps.locality,
        deps.resolver,
    )


@pytest.mark.asyncio
async def test_first_run_skips_location_when_address_permission_is_missing():
    handler_input = _handler_input()
    deps = _deps()
    deps.locality.detect_device_location.return_value = {"_status": "permission_denied"}
    response = await _permission(deps).complete_first_run(handler_input)
    assert "don't currently have permission" in response["outputSpeech"]["ssml"]
    deps.onboarding.complete_without_location.assert_called_once_with(handler_input)


def test_notification_permission_gives_app_guidance_without_a_connection():
    handler_input = _handler_input()
    deps = _deps()

    response = _permission(deps).start_notifications(handler_input)

    assert "Manage Permissions" in response["outputSpeech"]["ssml"]
    assert not any(
        directive.get("type") == "Connections.StartConnection"
        for directive in response.get("directives", [])
    )


@pytest.mark.asyncio
async def test_profile_setup_without_permissions_gives_app_guidance_and_asks_for_a_city():
    handler_input = _handler_input()
    deps = _deps()
    response = await _permission(deps).start_profile(handler_input)

    speech = response["outputSpeech"]["ssml"]
    assert "Manage Permissions" in speech
    assert "Which town or city" in speech
    assert response["shouldEndSession"] is False
    directive = response["directives"][0]
    assert directive["type"] == "Dialog.ElicitSlot"
    assert directive["updatedIntent"]["name"] == "TownCaptureIntent"
    assert directive["slotToElicit"] == "townName"
    assert not any(
        directive.get("type") == "Connections.StartConnection"
        for directive in response.get("directives", [])
    )
    deps.onboarding.begin_town_capture.assert_called_once_with(handler_input)
    store = deps.user.snapshot(handler_input)
    assert store["awaitingProfileTown"] is True
    assert store["profileSetupActive"] is True


@pytest.mark.asyncio
async def test_profile_setup_without_device_address_permission_gives_app_guidance_and_asks_for_a_city():
    handler_input = _handler_input()
    handler_input.request_envelope.context.System.user.permissions.scopes = {
        permission_scopes.PROFILE_NAME_READ: {"status": "GRANTED"},
        permission_scopes.PROFILE_EMAIL_READ: {"status": "GRANTED"},
    }
    deps = _deps()
    deps.locality.detect_device_location.return_value = {"_status": "permission_denied"}

    response = await _permission(deps).start_profile(handler_input)

    speech = response["outputSpeech"]["ssml"]
    assert "Manage Permissions" in speech
    assert "Which town or city" in speech
    deps.listener_profile.apply_listener_profile.assert_awaited_once_with(handler_input)


@pytest.mark.asyncio
async def test_first_run_does_not_open_a_permission_connection_when_address_is_missing():
    handler_input = _handler_input()
    deps = _deps()
    deps.locality.detect_device_location.return_value = {"_status": "permission_denied"}
    response = await _permission(deps).complete_first_run(handler_input)
    speech = response["outputSpeech"]["ssml"]
    assert "don't currently have permission to read the address" in speech
    assert not any(
        directive.get("type") == "Connections.StartConnection"
        for directive in response.get("directives", [])
    )


@pytest.mark.asyncio
async def test_address_city_is_saved_when_coordinate_resolution_has_no_match():
    handler_input = _handler_input()
    deps = _deps()
    deps.locality.detect_device_location.return_value = {
        "_status": "resolved",
        "city": "Manchester",
        "latitude": None,
        "longitude": None,
    }
    deps.resolver.resolve_utterance.return_value = {"resolution": {"match": None}}

    match = await _permission(deps)._resolved_location(handler_input)

    assert match == {
        "_status": "resolved",
        "city": "Manchester",
        "locality": "Manchester",
        "latitude": None,
        "longitude": None,
        "source": "device",
    }
    deps.resolver.resolve_utterance.assert_awaited_once_with(
        "Manchester",
        alexa_user_id="user",
        prefer_location=True,
        timeout_ms=5000,
    )


def test_permission_policy_has_no_platform_dependency():
    source = (Path(__file__).parents[1] / "src/models/permission_policy.py").read_text(
        encoding="utf-8"
    )
    assert "src.alexa" not in source
    assert "handler_input" not in source


def test_guest_sync_contains_only_alexa_identity_fields():
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
    Listener.set_identity(
        handler_input,
        IdentityContext(
            PrincipalType.SKILL_USER,
            alexa_user_id="user",
            device_id="amzn1.ask.device.TEST",
        ),
    )
    payload = ListenerSyncPayload.build(handler_input, store)
    assert payload == {
        "action": "alexa",
        "alexaUserId": "user",
        "listenerId": None,
        "deviceId": "amzn1.ask.device.TEST",
        "listenerName": "Hidden Name",
        "city": "Manchester",
        "latitude": 53.48,
        "longitude": -2.24,
    }


def test_listener_sync_uses_publication_history_subject_instead_of_track():
    handler_input = _handler_input()
    store = User.snapshot(handler_input)
    store["playHistory"] = [
        {
            "contentId": "track-2",
            "publicationId": "publication-1",
            "publicationTitle": "Weekly publication",
            "audioUrl": "https://cdn.hear.media/track-2.mp3",
            "trackIndex": 1,
            "trackCount": 2,
            "timeSpentMs": 2700000,
            "timeSpentHours": 0.75,
            "tracks": {
                "track-1": {"contentId": "track-1", "timeSpentMs": 1800000},
                "track-2": {"contentId": "track-2", "timeSpentMs": 900000},
            },
        }
    ]

    Listener.set_identity(
        handler_input,
        IdentityContext(PrincipalType.SKILL_USER, alexa_user_id="user"),
    )
    payload = ListenerSyncPayload.build(handler_input, store)

    assert "recentPlayedIds" not in payload
    assert "recentPlays" not in payload
    assert "playCount" not in payload
    assert "listeningPattern" not in payload


def test_environment_specific_permission_guidance(monkeypatch):
    monkeypatch.setattr("src.models.permission_policy.settings.STAGE", "production")
    assert "Hear service" in PermissionPolicy.app_guidance()
    monkeypatch.setattr("src.models.permission_policy.settings.STAGE", "development")
    assert "test development" in PermissionPolicy.app_guidance()
