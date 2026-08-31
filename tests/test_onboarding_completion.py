from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.alexa.runtime import AttrDict, ResponseBuilder
from src.clients.resolver import ResolverClient
from src.container import ApplicationContainer
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
    assert "read::alexa:device:all:address" in card.get("permissions", [])
    assert "alexa::devices:all:geolocation:read" not in card.get("permissions", [])
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
    await Onboarding.auto_detect_location_or_manual(
        mock_handler_input,
        User.snapshot(mock_handler_input),
        deps=ApplicationContainer(locality=locality, resolver=resolver),
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
