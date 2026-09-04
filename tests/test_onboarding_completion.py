from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.alexa.runtime import AttrDict, ResponseBuilder
from src.clients.resolver import ResolverClient
from src.container import ApplicationContainer
from src.models.affirmative import Affirmative
from src.models.onboarding import Onboarding
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
    await Onboarding.finalize_town_captured(
        mock_handler_input, {}, "Burnley", deps=ApplicationContainer()
    )
    store = User.snapshot(mock_handler_input)
    assert store["userCity"] == "Burnley"
    assert store["locality"] == "Burnley"
    assert store["onboardingComplete"] is True
    assert store["onboardingStage"] is None


def test_handle_permission_yes_sends_permission_card(mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.attributes_manager.set_session_attributes = MagicMock()
    mock_handler_input.response_builder = ResponseBuilder()
    result = Onboarding.handle_permission_yes(mock_handler_input, {}, deps=ApplicationContainer())
    card = result.get("card")
    assert card is not None, "handle_permission_yes must include a card in the response"
    assert card.get("type") == "AskForPermissionsConsent"
    assert card.get("permissions") == ["alexa::devices:all:geolocation:read"]
    assert result.get("shouldEndSession") is True


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
    await Onboarding.auto_detect_location_or_manual(
        mock_handler_input,
        User.snapshot(mock_handler_input),
        deps=ApplicationContainer(
            locality=locality,
            resolver=resolver,
            progressive=progressive,
        ),
    )
    pending = User.snapshot(mock_handler_input)["pendingLocationConfirm"]
    speech = mock_handler_input.response_builder.response["outputSpeech"]["ssml"]
    assert "Your Alexa device location is set to Burnley" in speech
    assert "Should I use Burnley for your local content?" in speech
    assert "I found" not in speech
    assert pending["latitude"] == 53.789
    assert pending["longitude"] == -2.248
    assert pending["postalCode"] == "BB10 1AA"
    assert pending["source"] == "device"
    progressive.send.assert_awaited_once_with(
        mock_handler_input,
        "One moment while I check that for you.",
    )
    resolver.resolve_utterance.assert_awaited_once_with(
        "Burnley",
        alexa_user_id="amzn1.ask.account.TEST",
        prefer_location=True,
        timeout_ms=5000,
    )


@pytest.mark.asyncio
async def test_empty_device_address_explains_missing_saved_city_and_allows_manual_entry(
    mock_handler_input,
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.response_builder = ResponseBuilder()
    mock_handler_input.attributes_manager.set_session_attributes = MagicMock()
    locality = SimpleNamespace(detect_device_location=AsyncMock(return_value={"_status": "empty"}))
    result = await Onboarding.auto_detect_location_or_manual(
        mock_handler_input,
        User.snapshot(mock_handler_input),
        deps=ApplicationContainer(locality=locality),
    )
    speech = result["outputSpeech"]["ssml"]
    assert "permission is enabled" in speech
    assert "couldn't find a location saved for this device" in speech
    assert "say skip" in result["outputSpeech"]["ssml"]
    assert User.snapshot(mock_handler_input)["onboardingStage"] == "ask_town"


@pytest.mark.asyncio
async def test_geolocation_coordinates_do_not_call_resolver(mock_handler_input):
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

    result = await Onboarding.auto_detect_location_or_manual(
        mock_handler_input,
        User.snapshot(mock_handler_input),
        deps=ApplicationContainer(
            locality=locality,
            resolver=resolver,
            progressive=progressive,
        ),
    )

    speech = result["outputSpeech"]["ssml"]
    pending = User.snapshot(mock_handler_input)["pendingLocationConfirm"]
    assert "I've found your device location" in speech
    assert pending["latitude"] == 53.789
    assert pending["longitude"] == -2.248
    assert pending["source"] == "geolocation"
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

    result = await Affirmative(
        deps=ApplicationContainer(user=user)
    )._confirm_location(mock_handler_input, user.snapshot(mock_handler_input), {})

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

    await Onboarding.stage_town_confirmation(
        mock_handler_input,
        User.snapshot(mock_handler_input),
        "Burnley",
        deps=ApplicationContainer(resolver=resolver, progressive=progressive),
    )

    progressive.send.assert_awaited_once_with(
        mock_handler_input,
        "One moment while I check that for you.",
    )


def test_third_failed_city_attempt_gives_device_setup_guidance(mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.response_builder = ResponseBuilder()
    store = User.snapshot(mock_handler_input)
    store.update({"onboardingStage": "ask_town", "onboardingTownAttempts": 2})
    result = Onboarding.resume_town_capture(mock_handler_input, store, deps=ApplicationContainer())
    speech = result["outputSpeech"]["ssml"]
    assert "update Device Location for this Echo" in speech
    assert "relaunch Hear" in speech
    assert "say skip" in speech
    assert User.snapshot(mock_handler_input)["onboardingComplete"] is False
    assert User.snapshot(mock_handler_input)["onboardingTownAttempts"] == 3
