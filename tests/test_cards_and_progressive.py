from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.alexa.runtime import AttrDict, ResponseBuilder
from src.clients.progressive import ProgressiveResponseClient


def test_simple_and_standard_cards_serialize() -> None:
    simple = ResponseBuilder().with_simple_card("Hear", "Try news").response
    assert simple["card"] == {"type": "Simple", "title": "Hear", "content": "Try news"}
    standard = (
        ResponseBuilder()
        .with_standard_card(
            "Recording",
            "A short description",
            small_image_url="https://images.example/small.png",
            large_image_url="https://images.example/large.png",
        )
        .response
    )
    assert standard["card"]["type"] == "Standard"
    assert standard["card"]["image"]["largeImageUrl"].endswith("large.png")
    invalid = (
        ResponseBuilder()
        .with_standard_card(
            "Recording", "Description", small_image_url="http://example.test/image.gif"
        )
        .response
    )
    assert "image" not in invalid["card"]


class _Pool:
    def __init__(self, response):
        self.client = SimpleNamespace(post=AsyncMock(return_value=response))

    def get(self):
        return self.client


def _handler_input(request_type: str = "IntentRequest"):
    request_attributes = {}
    return SimpleNamespace(
        request_envelope=AttrDict(
            {
                "context": {
                    "System": {
                        "apiEndpoint": "https://api.eu.amazonalexa.com",
                        "apiAccessToken": "secret-token",
                    }
                },
                "request": {"type": request_type, "requestId": "request-123"},
            }
        ),
        attributes_manager=SimpleNamespace(get_request_attributes=lambda: request_attributes),
    )


@pytest.mark.asyncio
async def test_progressive_response_sends_expected_directive_once() -> None:
    pool = _Pool(SimpleNamespace(status_code=204))
    client = ProgressiveResponseClient(pool=pool, enabled=True)
    handler_input = _handler_input()
    assert await client.send(handler_input, "One moment.") is True
    assert await client.send(handler_input, "Again.") is False
    call = pool.client.post.await_args
    assert call.args[0] == "https://api.eu.amazonalexa.com/v1/directives"
    assert call.kwargs["headers"]["Authorization"] == "Bearer secret-token"
    payload = call.kwargs["json"]
    assert payload["header"] == {"requestId": "request-123"}
    assert payload["directive"]["type"] == "VoicePlayer.Speak"
    assert payload["directive"]["speech"].startswith("<speak>")
    assert "One moment." in payload["directive"]["speech"]


@pytest.mark.asyncio
async def test_progressive_response_excludes_audio_player_and_is_best_effort() -> None:
    audio_pool = _Pool(SimpleNamespace(status_code=204))
    audio_client = ProgressiveResponseClient(pool=audio_pool, enabled=True)
    assert (
        await audio_client.send(_handler_input("AudioPlayer.PlaybackNearlyFinished"), "One moment.")
        is False
    )
    audio_pool.client.post.assert_not_awaited()
    failing_pool = _Pool(SimpleNamespace(status_code=500))
    failing_client = ProgressiveResponseClient(pool=failing_pool, enabled=True)
    assert await failing_client.send(_handler_input(), "One moment.") is False
