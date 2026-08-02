from __future__ import annotations

import pytest

from src.services.alexa.client import send_playback_events


@pytest.mark.asyncio
async def test_playback_dispatch_reports_queue_success(monkeypatch):
    monkeypatch.setattr(
        "src.services.alexa.client.dispatch",
        lambda *args, **kwargs: True,
    )

    result = await send_playback_events(
        alexa_user_id="user-1",
        events=[{
            "contentId": "content-1",
            "sessionId": "session-1",
            "eventType": "started",
        }],
    )

    assert result == {"status": "dispatched", "dispatched": 1, "failed": 0}


@pytest.mark.asyncio
async def test_playback_dispatch_reports_queue_failure(monkeypatch):
    monkeypatch.setattr(
        "src.services.alexa.client.dispatch",
        lambda *args, **kwargs: False,
    )

    result = await send_playback_events(
        alexa_user_id="user-1",
        events=[{
            "contentId": "content-1",
            "sessionId": "session-1",
            "eventType": "started",
        }],
    )

    assert result == {"status": "failed", "dispatched": 0, "failed": 1}
