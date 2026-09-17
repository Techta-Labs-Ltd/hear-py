from __future__ import annotations

import asyncio
import json

from src.alexa.request import AlexaRequest
from src.clients.events import BackendEventEnvelope, SqsEventClient, WebhookEventClient
from src.constants.events import EventConstants
from src.services.logging_control import ApplicationLog
from src.utils.deadline import RequestDeadline
from src.utils.events import EventUtils, SqsBatch
from src.utils.playback import PlaybackUtils


class OutboundEventService:
    __slots__ = ("_producer", "_webhook", "_stage_event")

    def __init__(
        self,
        producer: SqsEventClient | None = None,
        webhook: WebhookEventClient | None = None,
        stage_event=None,
    ) -> None:
        self._producer = producer
        self._webhook = webhook
        self._stage_event = stage_event

    def publish(self, event_type: str, data: dict, *, handler_input=None) -> bool:
        envelope = EventUtils.envelope(event_type, data)
        if self._stage_event is not None and handler_input is not None:
            return bool(self._stage_event(handler_input, envelope))
        if self._producer is None or not self._producer.enabled:
            return False
        return self._producer.send(envelope)

    @staticmethod
    def _operation_id(handler_input) -> str | None:
        request_id = AlexaRequest.get_request_id(handler_input) if handler_input is not None else None
        return request_id or None

    def playback(
        self,
        *,
        alexa_user_id: str,
        listener_id: str | None,
        state: dict,
        event_type: str,
        handler_input=None,
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
                "timeSpentMs": state.get("timeSpentMs") or 0,
                "publicationId": state.get("publicationId"),
                "subjectSessionId": state.get("subjectSessionId"),
                "trackIndex": state.get("trackIndex"),
                "trackCount": state.get("trackCount"),
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
        return self.publish(
            f"{EventConstants.PLAYBACK_PREFIX}{normalized_type}", event, handler_input=handler_input
        )

    def feedback(
        self,
        *,
        alexa_user_id: str,
        listener_id: str | None,
        pending: dict,
        value: str,
        handler_input=None,
    ) -> bool:
        payload = EventUtils.feedback_payload(
            alexa_user_id=alexa_user_id,
            listener_id=listener_id,
            pending=pending,
            value=value,
        )
        return bool(
            payload and self.publish(EventConstants.FEEDBACK_GIVEN, payload, handler_input=handler_input)
        )

    def following(
        self,
        *,
        followed: bool,
        alexa_user_id: str,
        listener_id: str | None,
        source: dict,
        handler_input,
    ) -> bool:
        source_id = source.get("id")
        source_name = source.get("name")
        source_type = source.get("type") or "creator"
        if not source_id:
            return False
        operation_id = self._operation_id(handler_input)
        if not operation_id:
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
                "listenerId": listener_id,
                "sourceType": "organization" if organization else "creator",
                "sourceId": str(source_id),
                "sourceName": source_name,
                "notificationSubjectType": EventConstants.PUBLICATION,
                "timestamp": EventUtils.timestamp_ms(),
                "clientEventId": (
                    f"follow:{listener_id or alexa_user_id}:"
                    f"{'follow' if followed else 'unfollow'}:{source_type}:{source_id}"
                    f":{operation_id}"
                ),
            }
        )
        return self.publish(event_type, payload, handler_input=handler_input)

    def report(
        self,
        *,
        alexa_user_id: str,
        listener_id: str | None,
        report: dict,
        handler_input,
    ) -> bool:
        subject_type = report.get("subjectType")
        event_type = (
            EventConstants.REPORTED_CREATOR
            if subject_type == "creator"
            else EventConstants.REPORTED_CONTENT
        )
        operation_id = self._operation_id(handler_input)
        if not operation_id:
            return False
        payload = {
            **report,
            "alexaUserId": alexa_user_id,
            "listenerId": listener_id,
            "reason": "reported_via_alexa",
            "clientEventId": (
                f"alexa-report:{listener_id or alexa_user_id}:"
                f"{subject_type}:{report.get('subjectId')}:{operation_id}"
            ),
        }
        return self.publish(event_type, EventUtils.compact(payload), handler_input=handler_input)

    def notification_preference(
        self,
        *,
        enabled: bool,
        alexa_user_id: str,
        listener_id: str | None,
        permission_granted: bool,
        handler_input=None,
    ) -> bool:
        event_type = (
            EventConstants.NOTIFICATIONS_ENABLED
            if enabled
            else EventConstants.NOTIFICATIONS_DISABLED
        )
        timestamp = EventUtils.timestamp_ms()
        payload = EventUtils.compact(
            {
                "alexaUserId": alexa_user_id,
                "listenerId": listener_id,
                "enabled": enabled,
                "permissionGranted": permission_granted,
                "timestamp": timestamp,
                "clientEventId": (
                    f"notifications:{listener_id or alexa_user_id}:"
                    f"{'enabled' if enabled else 'disabled'}:{timestamp}"
                ),
            }
        )
        return self.publish(event_type, payload, handler_input=handler_input)

    async def consume(
        self, records: list[dict], *, deadline: RequestDeadline | None = None
    ) -> dict:
        message_ids = SqsBatch.message_ids(records)
        budget = deadline if deadline is not None else RequestDeadline.from_context(None)
        failures = []
        for record, message_id in zip(records, message_ids):
            try:
                envelope = json.loads(
                    record.get("body") or "", parse_constant=EventUtils.reject_non_finite
                )
                BackendEventEnvelope.model_validate(envelope)
                remaining_ms = budget.remaining_ms(300)
                if remaining_ms <= 0:
                    delivered = False
                else:
                    delivered = bool(
                        self._webhook
                        and await asyncio.wait_for(
                            self._webhook.send(envelope), timeout=remaining_ms / 1000.0
                        )
                    )
            except Exception as exc:
                ApplicationLog.warning("Hear outbound record failed error=%s", type(exc).__name__)
                delivered = False
            if not delivered:
                failures.append({"itemIdentifier": message_id})
        return {"batchItemFailures": failures}
