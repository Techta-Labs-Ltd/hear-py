from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.clients.proactive import ProactiveEventPayload, ProactiveEventsClient
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.database.dynamodb import DynamoExpressions
from src.models.launch_workflow import LaunchWorkflow
from src.models.onboarding import LaunchTracker
from src.models.search import Search
from src.models.user import User
from src.services.notification_delivery import NotificationDeliveryService


class FakeInbox:
    def __init__(self, items=None):
        self.enabled = True
        self.items = list(items or [])
        self.statuses = []
        self.deliveries = []

    async def pending(self, listener_id, limit=5):
        return [item for item in self.items if item["listenerId"] == listener_id][:limit]

    async def set_status(self, listener_id, notification_id, status):
        self.statuses.append((listener_id, notification_id, status))

    async def set_delivery(
        self,
        listener_id,
        notification_id,
        status,
        *,
        http_status=None,
        error_code=None,
    ):
        self.deliveries.append(
            (listener_id, notification_id, status, http_status, error_code)
        )


class FakeHearApi:
    def __init__(self, result):
        self.result = result
        self.payload = None

    async def search(self, payload, timeout_ms=None):
        del timeout_ms
        self.payload = payload
        return self.result


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
    def content():
        return {
            "schemaVersion": 1,
            "listenerId": "listener-1",
            "notificationId": "notification-1",
            "notificationType": "content",
            "contentId": "content-1",
            "title": "The morning bulletin",
            "creatorId": "creator-1",
            "creatorName": "Pendle Voice",
            "organizationId": "organization-1",
            "organizationName": "Pendle Voice",
            "alexaUserId": "amzn1.ask.account.TEST",
            "locale": "en-GB",
            "publishedAt": 1_788_430_000,
            "status": "pending",
            "deliveryStatus": "pending",
            "sendProactive": True,
            "expiresAt": 1_788_516_400,
        }

    @staticmethod
    def publication():
        item = NotificationExamples.content()
        item.update(
            {
                "notificationId": "publication:publication-1",
                "notificationType": "publication",
                "publicationId": "publication-1",
                "title": "The September edition",
            }
        )
        item.pop("contentId")
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
    inbox = FakeInbox([NotificationExamples.content()])
    deps = ApplicationContainer(notification_inbox=inbox)

    response = await deps.notifications.offer(mock_handler_input, explicit=True)

    assert response == {"response": True}
    assert inbox.statuses == [("listener-1", "notification-1", "offered")]
    store = User.snapshot(mock_handler_input)
    assert store["awaitingNotificationChoice"] is True
    assert store["pendingNotification"]["contentId"] == "content-1"
    assert "alexaUserId" not in store["pendingNotification"]
    assert "listenerId" not in store["pendingNotification"]
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "The morning bulletin" in spoken
    assert "Pendle Voice" in spoken


@pytest.mark.asyncio
async def test_automatic_notification_offer_runs_when_listener_returns_on_launch(
    mock_handler_input,
):
    NotificationTestSupport.prepare(mock_handler_input)
    inbox = FakeInbox([NotificationExamples.content()])
    deps = ApplicationContainer(notification_inbox=inbox)

    response = await deps.notifications.offer(mock_handler_input)

    assert response == {"response": True}
    assert inbox.statuses == [("listener-1", "notification-1", "offered")]
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
    inbox = FakeInbox([NotificationExamples.content()])
    deps = ApplicationContainer(notification_inbox=inbox)

    response = await deps.notifications.offer(mock_handler_input)

    assert response is None
    assert inbox.statuses == []
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
    inbox = FakeInbox([NotificationExamples.content()])
    deps = ApplicationContainer(notification_inbox=inbox)
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
    assert "The morning bulletin" in spoken
    assert "Yesterday's recording" not in spoken


@pytest.mark.asyncio
async def test_notification_accept_searches_exact_content_and_consumes_only_when_started(
    monkeypatch,
    mock_handler_input,
):
    item = NotificationExamples.content()
    compact_item = {
        key: value
        for key, value in item.items()
        if key not in {"alexaUserId", "listenerId", "status", "deliveryStatus"}
    }
    NotificationTestSupport.prepare(
        mock_handler_input,
        {
            "awaitingNotificationChoice": True,
            "pendingNotification": compact_item,
        },
    )
    inbox = FakeInbox([item])
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
        notification_inbox=inbox,
        heara=hear,
        progressive=FakeProgressive(),
    )
    auto_play = AsyncMock(return_value={"playing": True})
    monkeypatch.setattr(Search, "auto_play_first_from_search", auto_play)

    response = await deps.notifications.accept(mock_handler_input)

    assert response == {"playing": True}
    assert hear.payload["filter"] == {"contentIds": ["content-1"]}
    assert [status[2] for status in inbox.statuses] == ["resolving", "queued"]
    assert User.snapshot(mock_handler_input)["notificationPlayback"] == {
        "notificationId": "notification-1",
        "contentId": "content-1",
    }

    await deps.notifications.playback_started(mock_handler_input, "content-1")

    assert inbox.statuses[-1] == ("listener-1", "notification-1", "consumed")
    assert User.snapshot(mock_handler_input)["notificationPlayback"] is None


@pytest.mark.asyncio
async def test_publication_notification_searches_the_exact_publication(
    monkeypatch,
    mock_handler_input,
):
    item = NotificationExamples.publication()
    NotificationTestSupport.prepare(
        mock_handler_input,
        {
            "awaitingNotificationChoice": True,
            "pendingNotification": {
                key: value
                for key, value in item.items()
                if key not in {"alexaUserId", "listenerId", "status", "deliveryStatus"}
            },
        },
    )
    inbox = FakeInbox([item])
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
        notification_inbox=inbox,
        heara=hear,
        progressive=FakeProgressive(),
    )
    monkeypatch.setattr(
        Search,
        "auto_play_first_from_search",
        AsyncMock(return_value={"playing": True}),
    )

    await deps.notifications.accept(mock_handler_input)

    assert hear.payload["filter"] == {"publicationIds": ["publication-1"]}
    assert hear.payload["limit"] == 10
    assert hear.payload["sort"] == "latest"


@pytest.mark.asyncio
async def test_notification_playback_failure_returns_item_to_pending(mock_handler_input):
    item = NotificationExamples.content()
    NotificationTestSupport.prepare(
        mock_handler_input,
        {
            "notificationPlayback": {
                "notificationId": "notification-1",
                "contentId": "content-1",
            }
        },
    )
    inbox = FakeInbox([item])
    deps = ApplicationContainer(notification_inbox=inbox)

    await deps.notifications.playback_failed(mock_handler_input, "content-1")

    assert inbox.statuses == [("listener-1", "notification-1", "pending")]
    assert User.snapshot(mock_handler_input)["notificationPlayback"] is None


def test_proactive_media_event_uses_localized_content_and_unicast_audience():
    payload = ProactiveEventPayload.build(NotificationExamples.content())

    assert payload["event"]["name"] == "AMAZON.MediaContent.Available"
    assert payload["event"]["payload"]["availability"]["method"] == "STREAM"
    assert payload["localizedAttributes"] == [
        {
            "locale": "en-GB",
            "providerName": "Pendle Voice",
            "contentName": "The morning bulletin",
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

    result = await client.deliver(NotificationExamples.content())

    assert result == {"sent": True, "retryable": False, "httpStatus": 202}
    assert len(pool.client.calls) == 2
    assert pool.client.calls[1][0].endswith("/v1/proactiveEvents/stages/development")
    assert pool.client.calls[1][1]["headers"]["Authorization"] == "Bearer lwa-token"


@pytest.mark.asyncio
async def test_stream_consumer_reports_only_retryable_records():
    item = NotificationExamples.content()
    encoded = {key: DynamoExpressions.encode_value(value) for key, value in item.items()}
    inbox = FakeInbox([item])
    proactive = FakeProactive(
        {
            "sent": False,
            "retryable": True,
            "httpStatus": 503,
            "errorCode": "unavailable",
        }
    )
    service = NotificationDeliveryService(inbox, proactive)

    result = await service.consume(
        [
            {
                "eventName": "INSERT",
                "dynamodb": {"SequenceNumber": "123", "NewImage": encoded},
            },
            {
                "eventName": "MODIFY",
                "dynamodb": {"SequenceNumber": "456", "NewImage": encoded},
            },
        ]
    )

    assert result == {"batchItemFailures": [{"itemIdentifier": "123"}]}
    assert inbox.deliveries == [
        ("listener-1", "notification-1", "retrying", 503, "unavailable")
    ]
