from __future__ import annotations

import json
import logging

from src.clients.events import SqsEventClient, WebhookEventClient
from src.constants.events import EventConstants
from src.utils.events import EventUtils
from src.utils.playback import PlaybackUtils


class OutboundEventService:
    logger = logging.getLogger(__name__)
    __slots__ = ("_producer", "_webhook")

    def __init__(
        self,
        producer: SqsEventClient | None = None,
        webhook: WebhookEventClient | None = None,
    ) -> None:
        self._producer = producer
        self._webhook = webhook

    def publish(self, event_type: str, data: dict) -> bool:
        if self._producer is None or not self._producer.enabled:
            return False
        return self._producer.send(EventUtils.envelope(event_type, data))

    def playback(
        self,
        *,
        alexa_user_id: str,
        listener_id: str | None,
        state: dict,
        event_type: str,
    ) -> bool:
        normalized_type = str(event_type or "event").strip().lower()
        event = PlaybackUtils.build_playback_event(
            {
                "contentId": state["contentId"],
                "sessionId": state["sessionId"],
                "eventType": normalized_type,
                "positionMs": state.get("offsetMs") or 0,
                "durationMs": state.get("durationMs") or 0,
                "listenedMs": state.get("listenedMs") or 0,
                "creatorId": state.get("creatorId"),
                "publicationId": state.get("publicationId"),
                "queueId": state.get("queueId"),
            }
        )
        event.update(
            EventUtils.compact(
                {
                    "alexaUserId": alexa_user_id,
                    "listenerId": listener_id,
                }
            )
        )
        return self.publish(f"{EventConstants.PLAYBACK_PREFIX}{normalized_type}", event)

    def feedback(
        self,
        *,
        alexa_user_id: str,
        listener_id: str | None,
        pending: dict,
        value: str,
    ) -> bool:
        payload = EventUtils.feedback_payload(
            alexa_user_id=alexa_user_id,
            listener_id=listener_id,
            pending=pending,
            value=value,
        )
        return bool(payload and self.publish(EventConstants.FEEDBACK_GIVEN, payload))

    def following(
        self,
        *,
        followed: bool,
        alexa_user_id: str,
        listener_id: str | None,
        source: dict,
    ) -> bool:
        source_id = source.get("id")
        source_name = source.get("name")
        source_type = source.get("type") or "creator"
        if not source_id:
            return False
        organization = source_type == "organization"
        if followed and organization:
            event_type = EventConstants.FOLLOWED_ORGANIZATION
        elif followed:
            event_type = EventConstants.FOLLOWED_CREATOR
        elif organization:
            event_type = EventConstants.UNFOLLOWED_ORGANIZATION
        else:
            event_type = EventConstants.UNFOLLOWED_CREATOR
        payload = EventUtils.compact(
            {
                "alexaUserId": alexa_user_id,
                "userId": alexa_user_id,
                "listenerId": listener_id,
                "sourceType": "organization" if organization else "creator",
                "sourceId": str(source_id),
                "sourceName": source_name,
                "timestamp": EventUtils.timestamp_ms(),
            }
        )
        return self.publish(event_type, payload)

    def report(
        self,
        *,
        alexa_user_id: str,
        listener_id: str | None,
        report: dict,
    ) -> bool:
        subject_type = report.get("subjectType")
        event_type = (
            EventConstants.REPORTED_CREATOR
            if subject_type == "creator"
            else EventConstants.REPORTED_CONTENT
        )
        payload = {
            **report,
            "alexaUserId": alexa_user_id,
            "userId": alexa_user_id,
            "listenerId": listener_id,
            "reason": "reported_via_alexa",
            "clientEventId": (
                f"alexa-report:{alexa_user_id}:{subject_type}:{report.get('subjectId')}"
            ),
        }
        return self.publish(event_type, EventUtils.compact(payload))

    async def consume(self, records: list[dict]) -> dict:
        failures = []
        for record in records:
            message_id = record.get("messageId")
            try:
                envelope = json.loads(record.get("body") or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            delivered = bool(self._webhook and await self._webhook.send(envelope))
            if not delivered and message_id:
                failures.append({"itemIdentifier": message_id})
        return {"batchItemFailures": failures}
