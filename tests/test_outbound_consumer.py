from __future__ import annotations

import json
from unittest.mock import AsyncMock

from src.webhooks.outbound_consumer import handler
from src.utils.webhook_signing import signed_webhook_headers


def _sqs_event(*bodies: dict) -> dict:
    return {
        "Records": [
            {"messageId": f"message-{index}", "body": json.dumps(body)}
            for index, body in enumerate(bodies, start=1)
        ],
    }


def test_outbound_consumer_forwards_playback_and_feedback(monkeypatch):
    monkeypatch.setattr(
        "src.webhooks.outbound_consumer.settings.WEBHOOK_OUTBOUND_URL",
        "https://example.test/events",
    )
    monkeypatch.setattr(
        "src.webhooks.outbound_consumer.settings.WEBHOOK_OUTBOUND_SECRET",
        "secret",
    )
    response = type("Response", (), {"status_code": 200})()
    forward = AsyncMock(return_value=response)
    monkeypatch.setattr(
        "src.webhooks.outbound_consumer._forward_to_backend",
        forward,
    )
    event = _sqs_event(
        {"event": "playback.started", "data": {"contentId": "content-1"}},
        {"event": "feedback.given", "data": {"feedback": "enjoyed"}},
    )

    result = handler(event)

    assert result == {"batchItemFailures": []}
    assert [call.args[3]["event"] for call in forward.await_args_list] == [
        "playback.started",
        "feedback.given",
    ]


def test_outbound_consumer_retries_when_url_is_missing(monkeypatch):
    monkeypatch.setattr(
        "src.webhooks.outbound_consumer.settings.WEBHOOK_OUTBOUND_URL",
        "",
    )
    event = _sqs_event({"event": "playback.finished", "data": {}})

    assert handler(event) == {
        "batchItemFailures": [{"itemIdentifier": "message-1"}],
    }


def test_outbound_headers_include_api_key_and_signature():
    headers = signed_webhook_headers("{}", "secret", "hear-api-key")

    assert headers["X-Api-Key"] == "hear-api-key"
    assert headers["Content-Type"] == "application/json"
    assert headers["x-webhook-signature"].startswith("t=")
    assert headers["x-webhook-timestamp"]
