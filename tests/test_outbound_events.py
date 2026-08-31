from __future__ import annotations

import json

import pytest

from src.clients.alexa import AlexaClient
from src.clients.events import SqsEventClient
from src.container import ApplicationContainer
from src.models.feedback import FeedbackService
from src.models.playback import Playback
from src.models.report import Report
from src.models.social import FollowCreator
from src.models.user import User
from src.services.events import OutboundEventService


class SqsStub:
    def __init__(self) -> None:
        self.messages = []

    def send_message(self, **message):
        self.messages.append(message)
        return {"MessageId": "message-1"}


class EventProducerStub:
    def __init__(self) -> None:
        self.envelopes = []

    @property
    def enabled(self) -> bool:
        return True

    def send(self, envelope: dict) -> bool:
        self.envelopes.append(envelope)
        return True


class WebhookStub:
    def __init__(self, failed_events: set[str] | None = None) -> None:
        self.failed_events = failed_events or set()
        self.envelopes = []

    async def send(self, envelope: dict) -> bool:
        self.envelopes.append(envelope)
        return envelope.get("event") not in self.failed_events


def test_sqs_client_sends_one_canonical_envelope():
    sqs = SqsStub()
    client = SqsEventClient(
        queue_url="https://sqs.eu-west-1.amazonaws.com/123/hear-events",
        region="eu-west-1",
        client=sqs,
    )

    assert client.send({"event": "playback.finished", "data": {"contentId": "track-1"}})
    assert json.loads(sqs.messages[0]["MessageBody"]) == {
        "event": "playback.finished",
        "data": {"contentId": "track-1"},
    }


@pytest.mark.asyncio
async def test_content_feedback_event_owns_one_complete_track(mock_handler_input):
    producer = EventProducerStub()
    service = FeedbackService(events=OutboundEventService(producer=producer))
    User.update(
        mock_handler_input,
        {
            "listenerId": "listener-1",
            "awaitingFeedback": True,
            "pendingFeedback": {
                "feedbackKey": "track-1",
                "subjectType": "content",
                "contentId": "track-1",
                "title": "Track one",
                "listenedMs": 120000,
                "completed": True,
            },
        },
    )

    await service.submit(mock_handler_input, "enjoyed")

    envelope = producer.envelopes[0]
    assert envelope["event"] == "feedback.given"
    assert envelope["data"]["subjectType"] == "content"
    assert envelope["data"]["subjectId"] == "track-1"
    assert envelope["data"]["contentId"] == "track-1"
    assert "contentIds" not in envelope["data"]


@pytest.mark.asyncio
async def test_publication_feedback_event_owns_the_whole_publication(
    mock_handler_input,
):
    producer = EventProducerStub()
    service = FeedbackService(events=OutboundEventService(producer=producer))
    User.update(
        mock_handler_input,
        {
            "listenerId": "listener-1",
            "awaitingFeedback": True,
            "pendingFeedback": {
                "feedbackKey": "publication:publication-1",
                "subjectType": "publication",
                "publicationId": "publication-1",
                "publicationTitle": "Weekly edition",
                "contentIds": ["track-1", "track-2"],
                "expectedTrackCount": 2,
                "meaningfulTrackCount": 2,
                "coverage": 1.0,
                "listenedMs": 240000,
                "completed": True,
            },
        },
    )

    await service.submit(mock_handler_input, "enjoyed")

    data = producer.envelopes[0]["data"]
    assert data["subjectType"] == "publication"
    assert data["subjectId"] == "publication-1"
    assert data["publicationId"] == "publication-1"
    assert data["contentIds"] == ["track-1", "track-2"]
    assert "contentId" not in data


@pytest.mark.asyncio
async def test_sqs_consumer_reports_only_failed_backend_deliveries():
    webhook = WebhookStub({"feedback.given"})
    service = OutboundEventService(webhook=webhook)
    records = [
        {
            "messageId": "message-1",
            "body": json.dumps({"event": "playback.finished", "data": {}}),
        },
        {
            "messageId": "message-2",
            "body": json.dumps({"event": "feedback.given", "data": {}}),
        },
    ]

    result = await service.consume(records)

    assert result == {"batchItemFailures": [{"itemIdentifier": "message-2"}]}


@pytest.mark.asyncio
async def test_playback_event_sends_the_track_with_publication_context(
    mock_handler_input,
):
    producer = EventProducerStub()
    playback = Playback(
        AlexaClient(),
        events=OutboundEventService(producer=producer),
    )
    state = {
        "contentId": "track-1",
        "publicationId": "publication-1",
        "sessionId": "session-1",
        "offsetMs": 120000,
        "durationMs": 180000,
        "listenedMs": 120000,
    }

    assert await playback.emit(mock_handler_input, "finished", state)

    envelope = producer.envelopes[0]
    assert envelope["event"] == "playback.finished"
    assert envelope["data"]["contentId"] == "track-1"
    assert envelope["data"]["publicationId"] == "publication-1"


@pytest.mark.asyncio
async def test_follow_action_sends_source_event_after_local_update(mock_handler_input):
    producer = EventProducerStub()
    events = OutboundEventService(producer=producer)
    deps = ApplicationContainer(events=events)
    User.update(
        mock_handler_input,
        {
            "activePlayback": {
                "contentId": "track-1",
                "organizationId": "organization-1",
                "organizationName": "York Talking News",
            }
        },
    )

    await FollowCreator(deps=deps).execute(mock_handler_input)

    envelope = producer.envelopes[0]
    assert envelope["event"] == "user.followed_organization"
    assert envelope["data"]["sourceId"] == "organization-1"
    assert User.snapshot(mock_handler_input)["followedCreators"] == [
        {
            "id": "organization-1",
            "name": "York Talking News",
            "type": "organization",
        }
    ]


@pytest.mark.asyncio
async def test_report_model_sends_the_recorded_backend_event(mock_handler_input):
    producer = EventProducerStub()
    report = Report(OutboundEventService(producer=producer))

    await report.record_report(
        mock_handler_input,
        {
            "type": "content",
            "id": "track-1",
            "name": "Track one",
            "contentId": "track-1",
            "publicationId": "publication-1",
        },
    )

    envelope = producer.envelopes[0]
    assert envelope["event"] == "user.reported_content"
    assert envelope["data"]["contentId"] == "track-1"
