from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone

from src.constants.events import EventConstants


class EventUtils:
    @staticmethod
    def timestamp_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def envelope(event_type: str, data: dict) -> dict:
        return {
            "event": str(event_type),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": data,
        }

    @staticmethod
    def sqs_message_attributes(envelope: dict) -> dict:
        data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
        values = {
            "eventType": envelope.get("event"),
            "subjectType": data.get("subjectType"),
            "subjectId": data.get("subjectId"),
            "publicationId": data.get("publicationId"),
            "notificationSubjectType": data.get("notificationSubjectType"),
        }
        return {
            key: {"DataType": "String", "StringValue": str(value)}
            for key, value in values.items()
            if value is not None and str(value).strip()
        }

    @staticmethod
    def compact(values: dict) -> dict:
        return {key: value for key, value in values.items() if value is not None}

    @staticmethod
    def feedback_payload(
        *,
        alexa_user_id: str,
        listener_id: str | None,
        pending: dict,
        value: str,
    ) -> dict | None:
        subject = EventUtils._feedback_subject(pending)
        if not subject:
            return None
        subject_type, subject_id, is_publication = subject
        recorded_at = EventUtils.timestamp_ms()
        payload = EventUtils.compact(
            {
                "alexaUserId": alexa_user_id,
                "listenerId": listener_id,
                "feedbackKey": pending.get("feedbackKey"),
                "subjectType": subject_type,
                "subjectId": str(subject_id),
                "title": pending.get("title"),
                "publicationTitle": pending.get("publicationTitle"),
                "creatorId": pending.get("creatorId"),
                "creatorName": pending.get("creatorName"),
                "organizationId": pending.get("organizationId"),
                "organizationName": pending.get("organizationName"),
                "category": pending.get("category"),
                "listenedMs": pending.get("listenedMs"),
                "timeSpentMs": pending.get("timeSpentMs"),
                "timeSpentHours": pending.get("timeSpentHours"),
                "trackListening": pending.get("trackListening")
                if is_publication
                else None,
                "feedback": str(value),
                "coverage": pending.get("coverage"),
                "expectedTrackCount": pending.get("expectedTrackCount"),
                "meaningfulTrackCount": pending.get("meaningfulTrackCount"),
                "timestamp": recorded_at,
                "clientEventId": (
                    f"feedback:{alexa_user_id}:{pending.get('feedbackKey') or subject_id}:{value}"
                ),
            }
        )
        payload.update(EventUtils._feedback_scope_fields(pending, is_publication))
        return payload

    @staticmethod
    def _feedback_subject(pending: dict) -> tuple[str, str, bool] | None:
        publication_id = pending.get("publicationId")
        content_id = pending.get("contentId")
        is_publication = pending.get("subjectType") == EventConstants.PUBLICATION and bool(
            publication_id
        )
        subject_type = EventConstants.PUBLICATION if is_publication else EventConstants.CONTENT
        subject_id = publication_id if is_publication else content_id
        return (subject_type, str(subject_id), is_publication) if subject_id else None

    @staticmethod
    def _feedback_scope_fields(pending: dict, is_publication: bool) -> dict:
        publication_id = pending.get("publicationId")
        if is_publication:
            return {
                "publicationId": str(publication_id),
                "contentIds": list(
                    dict.fromkeys(
                        str(item)
                        for item in pending.get("contentIds") or []
                        if item is not None and str(item).strip()
                    )
                ),
            }
        return EventUtils.compact(
            {
                "contentId": str(pending["contentId"]),
                "parentPublicationId": str(publication_id) if publication_id else None,
            }
        )

    @staticmethod
    def webhook_headers(
        body: str,
        secret: str,
        api_key: str,
        *,
        timestamp: int | None = None,
    ) -> dict:
        resolved_timestamp = int(timestamp or time.time())
        signature = hmac.new(
            secret.encode("utf-8"),
            f"{resolved_timestamp}.{body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "Content-Type": "application/json",
            "X-Api-Key": api_key,
            "x-webhook-signature": f"t={resolved_timestamp},v1={signature}",
            "x-webhook-timestamp": str(resolved_timestamp),
        }
