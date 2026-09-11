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
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = {**data, "action": EventConstants.ACTION}
        return {
            "event": str(event_type),
            "schemaVersion": EventConstants.CONTRACT_VERSION,
            "eventId": payload.get("clientEventId")
            or f"{event_type}:{EventUtils.timestamp_ms()}",
            "timestamp": created_at,
            "data": payload,
        }

    @staticmethod
    def sqs_message_attributes(envelope: dict) -> dict:
        data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
        values = {
            "eventType": envelope.get("event"),
            "eventId": envelope.get("eventId"),
            "schemaVersion": envelope.get("schemaVersion"),
            "action": data.get("action"),
            "listenerId": data.get("listenerId"),
            "subjectType": data.get("subjectType"),
            "contentId": data.get("contentId"),
            "publicationId": data.get("publicationId"),
            "sourceType": data.get("sourceType"),
            "sourceId": data.get("sourceId"),
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
        identity_id = listener_id or alexa_user_id
        payload = EventUtils.compact(
            {
                "alexaUserId": alexa_user_id,
                "listenerId": listener_id,
                "subjectType": subject_type,
                "contentId": str(subject_id) if not is_publication else None,
                "publicationId": str(subject_id) if is_publication else None,
                "trackListening": EventUtils._feedback_track_listening(pending)
                if is_publication
                else None,
                "feedback": str(value),
                "timestampMs": recorded_at,
                "clientEventId": (
                    f"feedback:{identity_id}:{pending.get('feedbackKey') or subject_id}:{value}"
                ),
            }
        )
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
    def _feedback_track_listening(pending: dict) -> list[dict]:
        tracks = pending.get("trackListening")
        if not isinstance(tracks, list):
            return []
        normalized = []
        for track in tracks:
            if not isinstance(track, dict) or not track.get("contentId"):
                continue
            normalized.append(
                EventUtils.compact(
                    {
                        "contentId": str(track["contentId"]),
                        "trackIndex": track.get("trackIndex"),
                        "durationMs": track.get("durationMs"),
                        "listenedMs": track.get("listenedMs"),
                        "timeSpentMs": track.get("timeSpentMs"),
                        "completed": track.get("completed"),
                    }
                )
            )
        return normalized

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
