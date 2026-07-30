from __future__ import annotations
import pytest
from src.handlers.intents.onboarding import finalize_town_captured
from src.runtime import AttrDict
from src.services.storage.persistence import get_store

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

    monkeypatch.setattr("src.handlers.intents.onboarding.resolve_utterance", resolve)
    mock_handler_input.request_envelope = AttrDict(
        mock_handler_input.request_envelope
    )
    await finalize_town_captured(mock_handler_input, {}, "Burnley")

    store = get_store(mock_handler_input)
    assert store["userCity"] == "Burnley"
    assert store["locality"] == "Burnley"
    assert store["onboardingComplete"] is True
    assert store["onboardingStage"] is None
