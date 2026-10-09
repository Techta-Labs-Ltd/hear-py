from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.alexa.launch import LaunchWorkflow
from src.alexa.onboarding import LaunchTracker
from src.alexa.runtime import ResponseBuilder
from src.alexa.search import Search
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.controllers.launch import TownCaptureHandler
from src.models.user import User


class FakeHearApi:
    def __init__(self, result=None, items=None):
        self.enabled = True
        self.result = result or {"results": [], "failed": False}
        self.items = list(items or [])
        self.payload = None
        self.notification_request = None
        self.statuses = []
        self.deliveries = []
        self.availability = AsyncMock()

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

    @staticmethod
    def publication(item):
        result = dict(item)
        result["publication"] = {
            "id": "publication-1",
            "title": "Morning Brief",
            "trackCount": 1,
        }
        return result


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
async def test_return_launch_prompts_unfinished_recording_before_new_update(
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

    response = await deps.build_request_launch_workflow(mock_handler_input).execute(mock_handler_input)

    assert response == {"response": True}
    store = User.snapshot(mock_handler_input)
    assert store["activeDialog"]["type"] == "resume"
    assert store["awaitingNotificationChoice"] is False
    assert store["awaitingResume"] is True
    assert hear.statuses == []
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "Yesterday's recording" not in spoken
    assert "new release from Pendle Voice" not in spoken


@pytest.mark.asyncio
async def test_creator_recording_update_searches_creator_and_consumes_on_start(
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
    assert hear.payload["filter"] == {"creatorIds": ["creator-1"]}
    hear.availability.assert_not_awaited()
    assert [status[2] for status in hear.statuses] == ["resolving", "queued"]
    assert User.snapshot(mock_handler_input)["notificationPlayback"] == {
        "notificationId": "notification-1",
        "contentId": "content-1",
    }

    await deps.notifications.playback_started(mock_handler_input, "content-1")

    assert hear.statuses[-1] == ("listener-1", "notification-1", "consumed")
    assert User.snapshot(mock_handler_input)["notificationPlayback"] is None


@pytest.mark.asyncio
async def test_organization_recording_update_searches_organization(
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

    assert hear.payload["filter"] == {"organizationIds": ["organization-1"]}
    assert hear.payload["limit"] == 10
    assert hear.payload["sort"] == "latest"
    hear.availability.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "item_factory",
    [
        lambda: NotificationExamples.publication(NotificationExamples.creator()),
        lambda: NotificationExamples.publication(NotificationExamples.organization()),
    ],
)
async def test_publication_notification_searches_exact_publication(
    monkeypatch,
    mock_handler_input,
    item_factory,
):
    item = item_factory()
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

    assert hear.payload["filter"] == {"publicationIds": ["publication-1"]}
    assert "publishedFrom" not in hear.payload["filter"]
    hear.availability.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_automatic_notification_offer_is_blocked_by_pending_feedback(
    mock_handler_input,
):
    NotificationTestSupport.prepare(
        mock_handler_input,
        {
            "awaitingFeedback": True,
            "pendingFeedback": {
                "feedbackKey": "content-1",
                "contentId": "content-1",
                "completed": True,
            },
        },
    )
    hear = FakeHearApi(items=[NotificationExamples.creator()])
    deps = ApplicationContainer(notification_api=hear)

    response = await deps.notifications.offer(mock_handler_input)

    assert response is None
    assert hear.statuses == []
    assert User.snapshot(mock_handler_input)["awaitingNotificationChoice"] is False


@pytest.mark.asyncio
async def test_followup_notification_offer_is_allowed_after_feedback_clears(
    mock_handler_input,
):
    NotificationTestSupport.prepare(mock_handler_input)
    mock_handler_input.request_envelope["request"] = {
        "type": "IntentRequest",
        "intent": {"name": "FeedbackResponseIntent", "slots": {}},
    }
    hear = FakeHearApi(items=[NotificationExamples.creator()])
    deps = ApplicationContainer(notification_api=hear)

    response = await deps.notifications.offer(mock_handler_input, followup=True)

    assert response == {"response": True}
    assert hear.statuses == [("listener-1", "notification-1", "offered")]
    assert User.snapshot(mock_handler_input)["awaitingNotificationChoice"] is True


@pytest.mark.asyncio
async def test_auto_notification_does_not_overlay_active_onboarding_dialog(
    mock_handler_input,
):
    NotificationTestSupport.prepare(
        mock_handler_input,
        {
            "onboardingComplete": True,
            "onboardingStage": "ask_town",
            "awaitingProfileTown": True,
            "profileSetupActive": True,
            "activeDialog": {
                "type": "onboarding",
                "context": {"stage": "ask_town"},
                "expiresAt": 4102444800,
            },
        },
    )
    hear = FakeHearApi(items=[NotificationExamples.creator()])
    deps = ApplicationContainer(notification_api=hear)

    response = await deps.notifications.offer(mock_handler_input)

    assert response is None
    assert hear.statuses == []
    store = User.snapshot(mock_handler_input)
    assert store["awaitingNotificationChoice"] is False
    assert store["activeDialog"]["type"] == "onboarding"


@pytest.mark.asyncio
async def test_notification_decline_owns_turn_and_clears_stale_profile_town_state(
    mock_handler_input,
):
    NotificationTestSupport.prepare(
        mock_handler_input,
        {
            "onboardingComplete": True,
            "playCount": 1,
            "onboardingStage": "ask_town",
            "awaitingProfileTown": True,
            "profileSetupActive": True,
            "pendingTownAmbiguity": {
                "phrase": "chelmsford",
                "candidates": [
                    {
                        "type": "location",
                        "id": "location-1826876670",
                        "name": "Chelmsford",
                    }
                ],
            },
            "awaitingNotificationChoice": True,
            "pendingNotification": None,
            "activeDialog": {
                "type": "notification",
                "context": {"question": "Would you like to listen?"},
                "expiresAt": 4102444800,
            },
        },
    )
    mock_handler_input.request_envelope["request"] = {
        "type": "IntentRequest",
        "intent": {"name": "AMAZON.NoIntent", "slots": {}},
    }
    mock_handler_input.response_builder = ResponseBuilder()
    deps = ApplicationContainer(notification_api=FakeHearApi(items=[]))

    assert deps.build_resolver_interceptor() is not None
    await deps.build_resolver_interceptor().process(mock_handler_input)
    town_handler = TownCaptureHandler(deps.build_town_capture(), deps.user)
    assert town_handler.can_handle(mock_handler_input) is False

    response = await deps.build_request_decline(mock_handler_input).execute(
        mock_handler_input
    )

    assert "leave that update for now" in response["outputSpeech"]["ssml"].casefold()
    store = User.snapshot(mock_handler_input)
    assert store["activeDialog"] is None
    assert store["awaitingNotificationChoice"] is False
    assert store["onboardingStage"] is None
    assert store["awaitingProfileTown"] is False
    assert store["profileSetupActive"] is False
    assert store["pendingTownAmbiguity"] is None


@pytest.mark.asyncio
async def test_return_launch_clears_profile_town_setup_before_notifications(
    monkeypatch,
    mock_handler_input,
):
    NotificationTestSupport.prepare(
        mock_handler_input,
        {
            "onboardingComplete": True,
            "playCount": 1,
            "onboardingStage": "ask_town",
            "awaitingProfileTown": True,
            "profileSetupActive": True,
            "activeDialog": {
                "type": "onboarding",
                "context": {"stage": "ask_town"},
                "expiresAt": 4102444800,
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

    response = await deps.build_request_launch_workflow(mock_handler_input).execute(
        mock_handler_input
    )

    assert response == {"response": True}
    assert hear.statuses == [("listener-1", "notification-1", "offered")]
    store = User.snapshot(mock_handler_input)
    assert store["onboardingStage"] is None
    assert store["awaitingProfileTown"] is False
    assert store["profileSetupActive"] is False
    assert store["activeDialog"]["type"] == "notification"
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "new release from Pendle Voice" in spoken
    assert "my city is" not in spoken.casefold()
