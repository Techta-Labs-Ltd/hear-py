from __future__ import annotations

import json
import logging

import pytest

from src.clients.alexa import AlexaClient
from src.clients.events import SqsEventClient, WebhookEventClient
from src.clients.pool import HttpCircuitOpen
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


class OpenCircuitPoolStub:
    def get(self):
        return self

    async def post(self, url, **kwargs):
        raise HttpCircuitOpen("HTTP dependency circuit is open")


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
    assert sqs.messages[0]["MessageAttributes"] == {
        "eventType": {"DataType": "String", "StringValue": "playback.finished"}
    }


@pytest.mark.asyncio
async def test_webhook_open_circuit_is_a_deferred_delivery_without_exception_log(caplog):
    client = WebhookEventClient(
        url="https://backend.hear.media/events",
        secret="secret",
        api_key="api-key",
        pool=OpenCircuitPoolStub(),
    )

    with caplog.at_level(logging.WARNING, logger="src.clients.events"):
        delivered = await client.send({"event": "playback.stopped", "data": {}})

    assert delivered is False
    assert "reason=circuit_open" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_publication_playback_event_reaches_sqs_as_publication(mock_handler_input):
    sqs = SqsStub()
    producer = SqsEventClient(
        queue_url="https://sqs.eu-west-1.amazonaws.com/123/hear-events",
        region="eu-west-1",
        client=sqs,
    )
    playback = Playback(
        AlexaClient(),
        events=OutboundEventService(producer=producer),
    )
    state = {
        "contentId": "track-2",
        "publicationId": "publication-1",
        "sessionId": "track-session-2",
        "subjectSessionId": "publication:publication-1:queue-1",
        "trackIndex": 1,
        "trackCount": 3,
        "offsetMs": 120000,
        "durationMs": 180000,
        "listenedMs": 120000,
        "timeSpentMs": 900000,
    }
    User.update(
        mock_handler_input,
        {
            "publicationFeedbackProgress": {
                "publication-1": {
                    "publicationId": "publication-1",
                    "timeSpentMs": 1800000,
                    "tracks": {
                        "track-1": {
                            "trackIndex": 0,
                            "durationMs": 900000,
                            "listenedMs": 900000,
                            "timeSpentMs": 900000,
                            "completed": True,
                        },
                        "track-2": {
                            "trackIndex": 1,
                            "durationMs": 180000,
                            "listenedMs": 120000,
                            "timeSpentMs": 900000,
                            "completed": False,
                        },
                    },
                }
            }
        },
    )

    assert await playback.emit(mock_handler_input, "stopped", state)

    message = sqs.messages[0]
    envelope = json.loads(message["MessageBody"])
    data = envelope["data"]
    assert envelope["event"] == "playback.stopped"
    assert data["subjectType"] == "publication"
    assert data["subjectId"] == "publication-1"
    assert data["publicationId"] == "publication-1"
    assert data["trackContentId"] == "track-2"
    assert data["timeSpentMs"] == 900000
    assert data["timeSpentHours"] == 0.25
    assert data["publicationTimeSpentMs"] == 1800000
    assert data["publicationTimeSpentHours"] == 0.5
    assert [track["contentId"] for track in data["trackListening"]] == [
        "track-1",
        "track-2",
    ]
    assert "contentId" not in data
    assert message["MessageAttributes"] == {
        "eventType": {"DataType": "String", "StringValue": "playback.stopped"},
        "subjectType": {"DataType": "String", "StringValue": "publication"},
        "subjectId": {"DataType": "String", "StringValue": "publication-1"},
        "publicationId": {"DataType": "String", "StringValue": "publication-1"},
    }


@pytest.mark.asyncio
async def test_publication_feedback_event_reaches_sqs_as_publication(mock_handler_input):
    sqs = SqsStub()
    producer = SqsEventClient(
        queue_url="https://sqs.eu-west-1.amazonaws.com/123/hear-events",
        region="eu-west-1",
        client=sqs,
    )
    service = FeedbackService(events=OutboundEventService(producer=producer))
    User.update(
        mock_handler_input,
        {
            "awaitingFeedback": True,
            "pendingFeedback": {
                "feedbackKey": "publication:publication-1",
                "subjectType": "publication",
                "publicationId": "publication-1",
                "publicationTitle": "Weekly edition",
                "contentIds": ["track-1", "track-2"],
                "timeSpentMs": 1800000,
                "timeSpentHours": 0.5,
                "trackListening": [
                    {"contentId": "track-1", "timeSpentMs": 900000},
                    {"contentId": "track-2", "timeSpentMs": 900000},
                ],
                "completed": True,
            },
        },
    )

    await service.submit(mock_handler_input, "enjoyed")

    message = sqs.messages[0]
    data = json.loads(message["MessageBody"])["data"]
    assert data["subjectType"] == "publication"
    assert data["subjectId"] == "publication-1"
    assert data["contentIds"] == ["track-1", "track-2"]
    assert data["timeSpentMs"] == 1800000
    assert data["timeSpentHours"] == 0.5
    assert len(data["trackListening"]) == 2
    assert "contentId" not in data
    assert message["MessageAttributes"]["subjectType"]["StringValue"] == "publication"
    assert message["MessageAttributes"]["subjectId"]["StringValue"] == "publication-1"


def test_follow_notification_event_reaches_sqs_with_publication_unit():
    sqs = SqsStub()
    producer = SqsEventClient(
        queue_url="https://sqs.eu-west-1.amazonaws.com/123/hear-events",
        region="eu-west-1",
        client=sqs,
    )
    service = OutboundEventService(producer=producer)

    assert service.following(
        followed=True,
        alexa_user_id="alexa-user-1",
        listener_id="listener-1",
        source={
            "type": "organization",
            "id": "organization-1",
            "name": "York Talking News",
        },
    )

    message = sqs.messages[0]
    envelope = json.loads(message["MessageBody"])
    assert envelope["event"] == "user.followed_organization"
    assert envelope["data"]["notificationSubjectType"] == "publication"
    assert message["MessageAttributes"]["notificationSubjectType"] == {
        "DataType": "String",
        "StringValue": "publication",
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
async def test_playback_event_uses_publication_as_subject_and_track_as_cursor(
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

    assert await playback.emit(mock_handler_input, "stopped", state)

    envelope = producer.envelopes[0]
    assert envelope["event"] == "playback.stopped"
    data = envelope["data"]
    assert data["subjectType"] == "publication"
    assert data["subjectId"] == "publication-1"
    assert data["publicationId"] == "publication-1"
    assert data["trackContentId"] == "track-1"
    assert "contentId" not in data


@pytest.mark.asyncio
async def test_playback_event_keeps_standalone_content_as_subject(mock_handler_input):
    producer = EventProducerStub()
    playback = Playback(
        AlexaClient(),
        events=OutboundEventService(producer=producer),
    )
    state = {
        "contentId": "track-1",
        "sessionId": "session-1",
        "offsetMs": 120000,
        "durationMs": 180000,
        "listenedMs": 120000,
    }

    assert await playback.emit(mock_handler_input, "stopped", state)

    data = producer.envelopes[0]["data"]
    assert data["subjectType"] == "content"
    assert data["subjectId"] == "track-1"
    assert data["contentId"] == "track-1"
    assert "publicationId" not in data
    assert "trackContentId" not in data


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
    assert envelope["data"]["notificationSubjectType"] == "publication"
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
