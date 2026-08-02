from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.resolver.location import resolve_location_phrase
from src.services import notifications


@pytest.fixture(autouse=True)
def memory_inbox(monkeypatch):
    notifications.reset_memory_notifications_for_tests()
    monkeypatch.setattr(
        notifications.settings,
        "HEAR_PERSISTENCE_DRIVER",
        "memory",
    )


@pytest.mark.asyncio
async def test_webhook_is_idempotent_per_recipient_and_requires_one_identifier():
    event = {
        "body": json.dumps({
            "eventId": "event-1",
            "notificationType": "content",
            "contentId": "content-1",
            "title": "Morning update",
            "alexaUserIds": ["user-1", "user-1"],
            "publishedAt": 1785300000,
        }),
    }
    assert (await notifications.handle_notification_webhook(event))["statusCode"] == 200
    assert (await notifications.handle_notification_webhook(event))["statusCode"] == 200
    assert len(await notifications.check_notifications("user-1")) == 1

    invalid = {
        "body": json.dumps({
            "eventId": "event-2",
            "notificationType": "content",
            "contentId": "content-1",
            "publicationId": "publication-1",
            "alexaUserIds": ["user-1"],
        }),
    }
    assert (await notifications.handle_notification_webhook(invalid))["statusCode"] == 400


@pytest.mark.asyncio
async def test_webhook_batches_large_recipient_lists_to_sqs(monkeypatch):
    sent = []
    client = type("Client", (), {"send_message": lambda self, **kwargs: sent.append(kwargs)})()
    monkeypatch.setattr(notifications.settings, "NOTIFICATION_INGEST_QUEUE_URL", "queue-url")
    monkeypatch.setattr(notifications.boto3, "client", lambda *args, **kwargs: client)

    response = await notifications.handle_notification_webhook({
        "body": json.dumps({
            "eventId": "event-batched",
            "notificationType": "content",
            "contentId": "content-1",
            "alexaUserIds": [f"user-{index}" for index in range(205)],
        }),
    })

    assert response["statusCode"] == 202
    assert len(sent) == 3
    assert [len(json.loads(message["MessageBody"])["alexaUserIds"]) for message in sent] == [100, 100, 5]


@pytest.mark.asyncio
async def test_content_batch_uses_one_search_and_consumes_only_after_start(
    monkeypatch,
    mock_handler_input,
):
    for index in range(5):
        await notifications.handle_notification_webhook({
            "body": json.dumps({
                "eventId": f"event-{index}",
                "notificationType": "content",
                "contentId": f"content-{index}",
                "title": f"Recording {index}",
                "alexaUserIds": ["amzn1.ask.account.TEST"],
                "publishedAt": 100 + index,
            }),
        })
    user_id = "amzn1.ask.account.TEST"
    pending = await notifications.check_notifications(user_id)
    search = AsyncMock(return_value={
        "failed": False,
        "results": [{
            "contentId": item["contentId"],
            "title": item["title"],
            "spokenTitle": item["title"],
            "audioUrl": f"https://cdn.hear.media/{item['contentId']}.mp3",
        } for item in pending],
    })
    monkeypatch.setattr(notifications, "search", search)

    resolved = await notifications.resolve_notification_queue(
        mock_handler_input,
        pending,
    )

    search.assert_awaited_once()
    assert search.await_args.args[0]["filter"]["contentIds"] == [
        item["contentId"] for item in pending
    ]
    assert len(resolved["queue"]["orderedContentIds"]) == 5
    cached = mock_handler_input.attributes_manager.request_attributes["_store"]["browseQueueItems"]
    assert [item["contentId"] for item in cached] == resolved["queue"]["orderedContentIds"]
    assert all(item["status"] == "queued" for item in await notifications.check_notifications(user_id))

    first = resolved["results"][0]["contentId"]
    await notifications.consume_notification_for_playback(user_id, first)
    remaining = await notifications.check_notifications(user_id)
    assert first not in {item.get("contentId") for item in remaining}


def test_manual_location_scope_resolves_burnley_with_coordinates():
    result = resolve_location_phrase("burnly")
    match = result["match"]
    assert match["city"] == "Burnley"
    assert match["countryCode"] == "gb"
    assert match["latitude"] == pytest.approx(53.789)
    assert match["longitude"] == pytest.approx(-2.248)
