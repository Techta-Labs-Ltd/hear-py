from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.clients.proactive import ProactiveEventPayload, ProactiveEventsClient
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.models.launch_workflow import LaunchWorkflow
from src.models.onboarding import LaunchTracker
from src.models.search import Search
from src.models.user import User
from src.services.notification_delivery import NotificationDeliveryService


class FakeHearApi:
    def __init__(self, result=None, items=None):
        self.enabled = True
        self.result = result or {"results": [], "failed": False}
        self.items = list(items or [])
        self.payload = None
        self.notification_request = None
        self.statuses = []
        self.deliveries = []

    async def search(self, payload, timeout_ms=None):
        del timeout_ms
        self.payload = payload
        return self.result

    async def pending(self, request, timeout_ms=None):
        del timeout_ms
        self.notification_request = dict(request)
        items = [
            item
            for item in self.items
            if item["listenerId"] == request["listenerId"]
            and (
                not request.get("notificationId")
                or item["notificationId"] == request["notificationId"]
            )
        ]
        return {"items": items[: request.get("limit", 5)], "failed": False}

    async def update(self, request, timeout_ms=None):
        del timeout_ms
        if request.get("status"):
            self.statuses.append(
                (request["listenerId"], request["notificationId"], request["status"])
            )
        if request.get("deliveryStatus"):
            self.deliveries.append(
                (
                    request["listenerId"],
                    request["notificationId"],
                    request["deliveryStatus"],
                    request.get("deliveryHttpStatus"),
                    request.get("deliveryErrorCode"),
                )
            )
        return {"updated": True, "retryable": False, "httpStatus": 200}


class FakeProgressive:
    async def send(self, handler_input, speech):
        del handler_input, speech
        return True


class FakeProactive:
    def __init__(self, result):
        self.result = result
        self.items = []

    async def deliver(self, item):
        self.items.append(item)
        return dict(self.result)


class FakeHttpResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self.body = body or {}

    def json(self):
        return dict(self.body)


class FakeHttpClient:
    def __init__(self):
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "auth/o2/token" in url:
            return FakeHttpResponse(200, {"access_token": "lwa-token", "expires_in": 3600})
        return FakeHttpResponse(202)


class FakeHttpPool:
    def __init__(self):
        self.client = FakeHttpClient()

    def get(self):
        return self.client


class NotificationExamples:
    @staticmethod
    def creator():
        return {
            "schemaVersion": 1,
            "listenerId": "listener-1",
            "notificationId": "notification-1",
            "notificationType": "creator_update",
            "sourceType": "creator",
            "sourceId": "creator-1",
            "sourceName": "Pendle Voice",
            "alexaUserId": "amzn1.ask.account.TEST",
            "locale": "en-GB",
            "lastDate": "2026-09-11T10:00:00Z",
            "sendProactive": True,
            "expiresAt": "2026-09-12T10:00:00Z",
        }

    @staticmethod
    def organization():
        item = NotificationExamples.creator()
        item.update(
            {
                "notificationId": "organization-update-1",
                "notificationType": "organization_update",
                "sourceType": "organization",
                "sourceId": "organization-1",
            }
        )
        return item


class NotificationTestSupport:
    @staticmethod
    def prepare(handler_input, store=None):
        handler_input.attributes_manager.request_attributes["_store"] = {
            **StateSchema.DEFAULT_STORE,
            "listenerId": "listener-1",
            **(store or {}),
        }
        builder = handler_input.response_builder
        builder.speak.return_value = builder
        builder.reprompt.return_value = builder
        builder.set_should_end_session.return_value = builder
        builder.add_directive.return_value = builder
        builder.response = {"response": True}


@pytest.mark.asyncio
async def test_notification_offer_uses_canonical_listener_and_persists_compact_dialog(
    mock_handler_input,
):
    NotificationTestSupport.prepare(mock_handler_input)
    hear = FakeHearApi(items=[NotificationExamples.creator()])
    deps = ApplicationContainer(notification_api=hear)

    response = await deps.notifications.offer(mock_handler_input, explicit=True)

    assert response == {"response": True}
    assert hear.statuses == [("listener-1", "notification-1", "offered")]
    store = User.snapshot(mock_handler_input)
    assert store["awaitingNotificationChoice"] is True
    assert store["pendingNotification"]["sourceId"] == "creator-1"
    assert "alexaUserId" not in store["pendingNotification"]
    assert "listenerId" not in store["pendingNotification"]
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "new release from Pendle Voice" in spoken
    assert "Pendle Voice" in spoken


@pytest.mark.asyncio
async def test_automatic_notification_offer_runs_when_listener_returns_on_launch(
    mock_handler_input,
):
    NotificationTestSupport.prepare(mock_handler_input)
    hear = FakeHearApi(items=[NotificationExamples.creator()])
    deps = ApplicationContainer(notification_api=hear)

    response = await deps.notifications.offer(mock_handler_input)

    assert response == {"response": True}
    assert hear.statuses == [("listener-1", "notification-1", "offered")]
    assert User.snapshot(mock_handler_input)["awaitingNotificationChoice"] is True


@pytest.mark.asyncio
async def test_automatic_notification_offer_never_interrupts_an_active_intent(
    mock_handler_input,
):
    NotificationTestSupport.prepare(mock_handler_input)
    mock_handler_input.request_envelope["request"] = {
        "type": "IntentRequest",
        "intent": {"name": "IncreaseSpeedIntent", "slots": {}},
    }
    hear = FakeHearApi(items=[NotificationExamples.creator()])
    deps = ApplicationContainer(notification_api=hear)

    response = await deps.notifications.offer(mock_handler_input)

    assert response is None
    assert hear.statuses == []
    assert User.snapshot(mock_handler_input)["awaitingNotificationChoice"] is False


@pytest.mark.asyncio
async def test_return_launch_offers_new_update_before_an_unfinished_recording(
    monkeypatch,
    mock_handler_input,
):
    NotificationTestSupport.prepare(
        mock_handler_input,
        {
            "onboardingComplete": True,
            "playCount": 1,
            "activePlayback": {
                "contentId": "old-content",
                "token": "old-content",
                "title": "Yesterday's recording",
                "audioUrl": "https://cdn.example.com/old-content.mp3",
                "status": "paused",
            },
        },
    )
    hear = FakeHearApi(items=[NotificationExamples.creator()])
    deps = ApplicationContainer(notification_api=hear)
    monkeypatch.setattr(LaunchTracker, "record", lambda *_args: {"save": {}})
    monkeypatch.setattr(
        LaunchWorkflow,
        "_ensure_listener_data_for_launch",
        AsyncMock(side_effect=lambda _handler_input, store: store),
    )
    monkeypatch.setattr(
        LaunchWorkflow,
        "_sync_listener_for_launch",
        AsyncMock(side_effect=lambda _handler_input, store: store),
    )

    response = await LaunchWorkflow(deps=deps).execute(mock_handler_input)

    assert response == {"response": True}
    store = User.snapshot(mock_handler_input)
    assert store["activeDialog"]["type"] == "notification"
    assert store["awaitingNotificationChoice"] is True
    assert store["awaitingResume"] is False
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "new release from Pendle Voice" in spoken
    assert "Yesterday's recording" not in spoken


@pytest.mark.asyncio
async def test_creator_update_searches_source_since_last_date_and_consumes_on_start(
    monkeypatch,
    mock_handler_input,
):
    item = NotificationExamples.creator()
    compact_item = {
        key: value
        for key, value in item.items()
        if key not in {"alexaUserId", "listenerId"}
    }
    NotificationTestSupport.prepare(
        mock_handler_input,
        {
            "awaitingNotificationChoice": True,
            "pendingNotification": compact_item,
        },
    )
    hear = FakeHearApi(
        {
            "results": [
                {
                    "contentId": "content-1",
                    "title": "The morning bulletin",
                    "audioUrl": "https://cdn.example.com/content-1.mp3",
                }
            ],
            "total_hits": 1,
            "failed": False,
        }
    )
    deps = ApplicationContainer(
        heara=hear,
        notification_api=hear,
        progressive=FakeProgressive(),
    )
    auto_play = AsyncMock(return_value={"playing": True})
    monkeypatch.setattr(Search, "auto_play_first_from_search", auto_play)

    response = await deps.notifications.accept(mock_handler_input)

    assert response == {"playing": True}
    assert hear.payload["filter"] == {
        "creatorIds": ["creator-1"],
        "publishedFrom": "2026-09-11T10:00:00Z",
    }
    assert [status[2] for status in hear.statuses] == ["resolving", "queued"]
    assert User.snapshot(mock_handler_input)["notificationPlayback"] == {
        "notificationId": "notification-1",
        "contentId": "content-1",
    }

    await deps.notifications.playback_started(mock_handler_input, "content-1")

    assert hear.statuses[-1] == ("listener-1", "notification-1", "consumed")
    assert User.snapshot(mock_handler_input)["notificationPlayback"] is None


@pytest.mark.asyncio
async def test_organization_update_searches_source_since_last_date(
    monkeypatch,
    mock_handler_input,
):
    item = NotificationExamples.organization()
    NotificationTestSupport.prepare(
        mock_handler_input,
        {
            "awaitingNotificationChoice": True,
            "pendingNotification": {
                key: value
                for key, value in item.items()
                if key not in {"alexaUserId", "listenerId"}
            },
        },
    )
    hear = FakeHearApi(
        {
            "results": [
                {
                    "contentId": "publication-track-1",
                    "publicationId": "publication-1",
                    "title": "Track one",
                    "audioUrl": "https://cdn.example.com/publication-track-1.mp3",
                }
            ],
            "failed": False,
        }
    )
    deps = ApplicationContainer(
        heara=hear,
        notification_api=hear,
        progressive=FakeProgressive(),
    )
    monkeypatch.setattr(
        Search,
        "auto_play_first_from_search",
        AsyncMock(return_value={"playing": True}),
    )

    await deps.notifications.accept(mock_handler_input)

    assert hear.payload["filter"] == {
        "organizationIds": ["organization-1"],
        "publishedFrom": "2026-09-11T10:00:00Z",
    }
    assert hear.payload["limit"] == 10
    assert hear.payload["sort"] == "latest"


@pytest.mark.asyncio
async def test_notification_playback_failure_returns_item_to_pending(mock_handler_input):
    item = NotificationExamples.creator()
    NotificationTestSupport.prepare(
        mock_handler_input,
        {
            "notificationPlayback": {
                "notificationId": "notification-1",
                "contentId": "content-1",
            }
        },
    )
    hear = FakeHearApi(items=[item])
    deps = ApplicationContainer(notification_api=hear)

    await deps.notifications.playback_failed(mock_handler_input, "content-1")

    assert hear.statuses == [("listener-1", "notification-1", "pending")]
    assert User.snapshot(mock_handler_input)["notificationPlayback"] is None


def test_proactive_media_event_uses_localized_content_and_unicast_audience():
    payload = ProactiveEventPayload.build(NotificationExamples.creator())

    assert payload["event"]["name"] == "AMAZON.MediaContent.Available"
    assert payload["event"]["payload"]["availability"]["method"] == "STREAM"
    assert payload["localizedAttributes"] == [
        {
            "locale": "en-GB",
            "providerName": "Pendle Voice",
            "contentName": "A new release from Pendle Voice",
        }
    ]
    assert payload["relevantAudience"]["payload"]["user"] == "amzn1.ask.account.TEST"
    assert payload["referenceId"].isalnum()


@pytest.mark.asyncio
async def test_proactive_client_gets_lwa_token_then_posts_to_europe_development_endpoint():
    pool = FakeHttpPool()
    client = ProactiveEventsClient(
        client_id="client-id",
        client_secret="client-secret",
        stage="development",
        pool=pool,
    )

    result = await client.deliver(NotificationExamples.creator())

    assert result == {"sent": True, "retryable": False, "httpStatus": 202}
    assert len(pool.client.calls) == 2
    assert pool.client.calls[1][0].endswith("/v1/proactiveEvents/stages/development")
    assert pool.client.calls[1][1]["headers"]["Authorization"] == "Bearer lwa-token"


@pytest.mark.asyncio
async def test_sqs_consumer_reports_only_retryable_records():
    item = NotificationExamples.creator()
    hear = FakeHearApi(items=[item])
    proactive = FakeProactive(
        {
            "sent": False,
            "retryable": True,
            "httpStatus": 503,
            "errorCode": "unavailable",
        }
    )
    service = NotificationDeliveryService(hear, proactive)

    result = await service.consume(
        [
            {
                "messageId": "123",
                "body": json.dumps(
                    {
                        "schemaVersion": 1,
                        "listenerId": "listener-1",
                        "notificationId": "notification-1",
                    }
                ),
            },
            {
                "messageId": "456",
                "body": json.dumps(
                    {
                        "schemaVersion": 1,
                        "listenerId": "listener-1",
                        "notificationId": "notification-2",
                    }
                ),
            },
        ]
    )

    assert result == {"batchItemFailures": [{"itemIdentifier": "123"}]}
    assert hear.deliveries == [
        ("listener-1", "notification-1", "retrying", 503, "unavailable")
    ]


@pytest.mark.asyncio
async def test_sqs_consumer_marks_successful_delivery_and_acknowledges_message():
    hear = FakeHearApi(items=[NotificationExamples.creator()])
    proactive = FakeProactive(
        {"sent": True, "retryable": False, "httpStatus": 202}
    )
    service = NotificationDeliveryService(hear, proactive)

    result = await service.consume(
        [
            {
                "messageId": "message-1",
                "body": json.dumps(
                    {
                        "schemaVersion": 1,
                        "listenerId": "listener-1",
                        "notificationId": "notification-1",
                    }
                ),
            }
        ]
    )

    assert result == {"batchItemFailures": []}
    assert proactive.items[0]["notificationId"] == "notification-1"
    assert hear.deliveries == [
        ("listener-1", "notification-1", "sent", 202, None)
    ]


@pytest.mark.asyncio
async def test_sqs_consumer_acknowledges_an_already_completed_notification():
    hear = FakeHearApi(items=[])
    proactive = FakeProactive(
        {"sent": True, "retryable": False, "httpStatus": 202}
    )
    service = NotificationDeliveryService(hear, proactive)

    result = await service.consume(
        [
            {
                "messageId": "message-1",
                "body": json.dumps(
                    {
                        "schemaVersion": 1,
                        "listenerId": "listener-1",
                        "notificationId": "notification-1",
                    }
                ),
            }
        ]
    )

    assert result == {"batchItemFailures": []}
    assert proactive.items == []
