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
        publication_id = pending.get("publicationId")
        content_id = pending.get("contentId")
        is_publication = pending.get("subjectType") == EventConstants.PUBLICATION and bool(
            publication_id
        )
        subject_type = EventConstants.PUBLICATION if is_publication else EventConstants.CONTENT
        subject_id = publication_id if is_publication else content_id
        if not subject_id:
            return None
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
        if is_publication:
            payload["publicationId"] = str(publication_id)
            payload["contentIds"] = list(
                dict.fromkeys(
                    str(item)
                    for item in pending.get("contentIds") or []
                    if item is not None and str(item).strip()
                )
            )
        else:
            payload["contentId"] = str(content_id)
            if publication_id:
                payload["parentPublicationId"] = str(publication_id)
        return payload

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
