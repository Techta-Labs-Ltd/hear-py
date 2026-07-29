from __future__ import annotations

import pytest

from src.handlers.intents.onboarding import finalize_town_captured
from src.runtime import AttrDict
from src.services.storage.persistence import get_store


@pytest.mark.asyncio
async def test_manual_town_capture_completes_onboarding(mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(
        mock_handler_input.request_envelope
    )
    await finalize_town_captured(mock_handler_input, {}, "Burnley")

    store = get_store(mock_handler_input)
    assert store["userCity"] == "Burnley"
    assert store["locality"] == "Burnley"
    assert store["onboardingComplete"] is True
    assert store["onboardingStage"] is None
