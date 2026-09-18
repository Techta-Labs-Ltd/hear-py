from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.alexa.onboarding import Onboarding
from src.alexa.runtime import AttrDict, ResponseBuilder
from src.clients.resolver import ResolverClient
from src.container import ApplicationContainer
from src.models.user import User


@pytest.mark.asyncio
async def test_manual_town_capture_completes_onboarding(monkeypatch, mock_handler_input):

    async def resolve(*args, **kwargs):
        return {
            "version": 1,
            "status": "resolved",
            "resolution": {
                "match": {
                    "city": "Burnley",
                    "locality": "Burnley",
                    "countryCode": "GB",
                    "latitude": 53.789,
                    "longitude": -2.248,
                },
                "candidates": [],
            },
        }

    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    await ApplicationContainer().finalize_town_captured(
        mock_handler_input, {}, "Burnley"
    )
    store = User.snapshot(mock_handler_input)
    assert store["userCity"] == "Burnley"
    assert store["locality"] == "Burnley"
    assert store["onboardingComplete"] is True
    assert store["onboardingStage"] is None


def test_handle_permission_no_finishes_onboarding_without_location(mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.attributes_manager.set_session_attributes = MagicMock()
    mock_handler_input.response_builder = ResponseBuilder()
    result = ApplicationContainer().handle_permission_no(mock_handler_input, {})
    assert "set up your listener profile later" in result["outputSpeech"]["ssml"]
    assert result.get("shouldEndSession") is False
    assert User.snapshot(mock_handler_input)["onboardingComplete"] is True


@pytest.mark.asyncio
async def test_device_address_city_is_resolved_to_coordinates_before_confirmation(
    mock_handler_input,
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.response_builder = ResponseBuilder()
    mock_handler_input.attributes_manager.set_session_attributes = MagicMock()
    locality = SimpleNamespace(
        detect_device_location=AsyncMock(
            return_value={
                "_status": "resolved",
                "city": "Burnley",
                "locality": "Burnley",
                "postalCode": "BB10 1AA",
                "countryCode": "GB",
                "latitude": None,
                "longitude": None,
                "source": "device",
            }
        )
    )
    resolver = SimpleNamespace(
        resolve_utterance=AsyncMock(
            return_value={
                "resolution": {
                    "match": {
                        "city": "Burnley",
                        "locality": "Burnley",
                        "countryCode": "GB",
                        "latitude": 53.789,
                        "longitude": -2.248,
                    }
                }
            }
        )
    )
    progressive = SimpleNamespace(send=AsyncMock(return_value=True))
    await ApplicationContainer(
        locality=locality,
        resolver=resolver,
        progressive=progressive,
    ).permission.complete_first_run(mock_handler_input)
    store = User.snapshot(mock_handler_input)
    speech = mock_handler_input.response_builder.response["outputSpeech"]["ssml"]
    assert "I found your location as Burnley" in speech
    assert store["latitude"] == 53.789
    assert store["longitude"] == -2.248
    assert store["devicePostalCode"] == "BB10 1AA"
    assert store["locationSource"] == "device"
    resolver.resolve_utterance.assert_awaited_once_with(
        "Burnley",
        alexa_user_id="amzn1.ask.account.TEST",
        prefer_location=True,
        timeout_ms=5000,
    )


@pytest.mark.asyncio
async def test_empty_device_address_skips_first_run_location(
    mock_handler_input,
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.response_builder = ResponseBuilder()
    mock_handler_input.attributes_manager.set_session_attributes = MagicMock()
    locality = SimpleNamespace(detect_device_location=AsyncMock(return_value={"_status": "empty"}))
    result = await ApplicationContainer(locality=locality).permission.complete_first_run(
        mock_handler_input
    )
    speech = result["outputSpeech"]["ssml"]
    assert "address permission is turned on" in speech
    assert "set up my account" in speech
    assert User.snapshot(mock_handler_input)["onboardingStage"] is None


@pytest.mark.asyncio
async def test_first_run_does_not_use_unrequested_geolocation(mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.response_builder = ResponseBuilder()
    mock_handler_input.attributes_manager.set_session_attributes = MagicMock()
    locality = SimpleNamespace(
        detect_device_location=AsyncMock(
            return_value={
                "_status": "resolved",
                "city": "",
                "locality": "",
                "countryCode": None,
                "postalCode": None,
                "latitude": 53.789,
                "longitude": -2.248,
                "source": "geolocation",
            }
        )
    )
    resolver = SimpleNamespace(resolve_utterance=AsyncMock())
    progressive = SimpleNamespace(send=AsyncMock(return_value=True))

    result = await ApplicationContainer(
        locality=locality,
        resolver=resolver,
        progressive=progressive,
    ).permission.complete_first_run(mock_handler_input)

    speech = result["outputSpeech"]["ssml"]
    assert "I found your location" not in speech
    resolver.resolve_utterance.assert_not_awaited()


@pytest.mark.asyncio
async def test_coordinate_only_location_can_be_confirmed(mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.response_builder = ResponseBuilder()
    mock_handler_input.attributes_manager.set_session_attributes = MagicMock()
    user = User()
    user.update(
        mock_handler_input,
        {
            "awaitingLocationConfirm": True,
            "pendingLocationConfirm": {
                "city": "",
                "locality": "",
                "latitude": 53.789,
                "longitude": -2.248,
                "source": "geolocation",
            },
        },
    )

    result = await ApplicationContainer(user=user).build_request_affirmative(mock_handler_input)._confirm_location(
        mock_handler_input, user.snapshot(mock_handler_input), {}
    )

    store = user.snapshot(mock_handler_input)
    assert store["onboardingComplete"] is True
    assert store["latitude"] == 53.789
    assert store["longitude"] == -2.248
    assert not store.get("userCity")
    assert "use your device location for local content" in result["outputSpeech"]["ssml"]


@pytest.mark.asyncio
async def test_manual_town_lookup_sends_location_progressive(mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.response_builder = ResponseBuilder()
    mock_handler_input.attributes_manager.set_session_attributes = MagicMock()
    resolver = SimpleNamespace(
        resolve_utterance=AsyncMock(
            return_value={
                "resolution": {
                    "match": {
                        "city": "Burnley",
                        "locality": "Burnley",
                        "countryCode": "GB",
                        "latitude": 53.789,
                        "longitude": -2.248,
                    }
                }
            }
        )
    )
    progressive = SimpleNamespace(send=AsyncMock(return_value=True))

    await ApplicationContainer(
        resolver=resolver,
        progressive=progressive,
    ).stage_town_confirmation(
        mock_handler_input,
        User.snapshot(mock_handler_input),
        "Burnley",
    )

    progressive.send.assert_awaited_once_with(
        mock_handler_input,
        "One moment while I check that for you.",
    )


def test_third_failed_city_attempt_keeps_manual_location_available(mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.response_builder = ResponseBuilder()
    store = User.snapshot(mock_handler_input)
    store.update({"onboardingStage": "ask_town", "onboardingTownAttempts": 2})
    container = ApplicationContainer()
    result = Onboarding.resume_town_capture(
        mock_handler_input, store, container.onboarding
    )
    speech = result["outputSpeech"]["ssml"]
    assert "set my location" in speech
    assert "relaunch Hear" not in speech
    assert User.snapshot(mock_handler_input)["onboardingComplete"] is False
    assert User.snapshot(mock_handler_input)["onboardingTownAttempts"] == 3
