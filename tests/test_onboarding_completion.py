from __future__ import annotations
import pytest
from unittest.mock import MagicMock
from src.handlers.onboarding import finalize_town_captured, handle_permission_yes
from src.clients.resolver import ResolverClient

from src.runtime import AttrDict
from src.services.store import get_store


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
    mock_handler_input.request_envelope = AttrDict(
        mock_handler_input.request_envelope
    )
    await finalize_town_captured(mock_handler_input, {}, "Burnley")

    store = get_store(mock_handler_input)
    assert store["userCity"] == "Burnley"
    assert store["locality"] == "Burnley"
    assert store["onboardingComplete"] is True
    assert store["onboardingStage"] is None


def test_handle_permission_yes_sends_permission_card(mock_handler_input):
    from src.runtime import ResponseBuilder
    mock_handler_input.request_envelope = AttrDict(
        mock_handler_input.request_envelope
    )
    mock_handler_input.attributes_manager.set_session_attributes = MagicMock()
    mock_handler_input.response_builder = ResponseBuilder()

    result = handle_permission_yes(mock_handler_input, {})

    card = result.get("card")
    assert card is not None, "handle_permission_yes must include a card in the response"
    assert card.get("type") == "AskForPermissionsConsent"
    assert "alexa::devices:all:address:full:read" in card.get("permissions", [])
    assert "alexa::devices:all:geolocation:read" in card.get("permissions", [])
