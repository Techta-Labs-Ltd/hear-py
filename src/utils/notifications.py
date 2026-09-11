from __future__ import annotations

import json

from src.constants.notifications import NotificationConstants


class NotificationItem:
    __slots__ = ()

    @staticmethod
    def normalize(item: dict | None) -> dict | None:
        source, notification, target = NotificationItem._parts(item)
        listener_id = str(
            source.get("listenerId") or notification.get("listenerId") or ""
        ).strip()
        notification_id = str(notification.get("notificationId") or "").strip()
        notification_type = str(
            notification.get("notificationType") or ""
        ).strip().casefold()
        source_type = str(notification.get("sourceType") or "").strip().casefold()
        source_id = str(notification.get("sourceId") or "").strip()
        source_name = NotificationItem.optional_text(notification.get("sourceName"))
        last_date = NotificationItem.optional_text(notification.get("lastDate"))
        if (
            not listener_id
            or not notification_id
            or notification_type
            not in {
                NotificationConstants.CREATOR_UPDATE,
                NotificationConstants.ORGANIZATION_UPDATE,
            }
            or not source_id
            or not source_name
            or not last_date
        ):
            return None
        if notification_type == NotificationConstants.CREATOR_UPDATE and source_type != "creator":
            return None
        if (
            notification_type == NotificationConstants.ORGANIZATION_UPDATE
            and source_type != "organization"
        ):
            return None
        return {
            key: value
            for key, value in {
                "schemaVersion": int(
                    notification.get("schemaVersion")
                    or NotificationConstants.SCHEMA_VERSION
                ),
                "listenerId": listener_id,
                "notificationId": notification_id,
                "notificationType": notification_type,
                "sourceType": source_type,
                "sourceId": source_id,
                "sourceName": source_name,
                "lastDate": last_date,
                "alexaUserId": NotificationItem.optional_text(
                    target.get("userId") or source.get("alexaUserId")
                ),
                "locale": NotificationItem.optional_text(target.get("locale"))
                or NotificationConstants.DEFAULT_LOCALE,
                "sendProactive": source.get("sendProactive") is not False,
                "expiresAt": NotificationItem.optional_text(
                    notification.get("expiresAt")
                ),
            }.items()
            if value is not None
        }

    @staticmethod
    def _parts(item: dict | None) -> tuple[dict, dict, dict]:
        source = item if isinstance(item, dict) else {}
        notification = source.get("notification")
        notification = notification if isinstance(notification, dict) else source
        target = source.get("deliveryTarget")
        target = target if isinstance(target, dict) else {}
        return source, notification, target

    @staticmethod
    def optional_text(value: object) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        return text

    @staticmethod
    def integer(value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def response_items(response: dict | list | None) -> list[dict]:
        source = response.get("data", response) if isinstance(response, dict) else response
        if isinstance(source, list):
            return [item for item in source if isinstance(item, dict)]
        if not isinstance(source, dict):
            return []
        if isinstance(source.get("notification"), dict) and (
            source.get("listenerId") or source.get("deliveryTarget")
        ):
            return [source]
        for key in ("notifications", "items", "results", "notification"):
            candidate = source.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
            if isinstance(candidate, dict):
                return [candidate]
        return [source] if source.get("notificationId") else []

    @staticmethod
    def matches_request(item: dict, request: dict) -> bool:
        notification_id = str(request.get("notificationId") or "").strip()
        return (
            item.get("listenerId") == request.get("listenerId")
            and (not notification_id or item.get("notificationId") == notification_id)
        )


class NotificationQueueMessage:
    __slots__ = ()

    @staticmethod
    def decode(record: dict) -> dict | None:
        try:
            decoded = json.loads(record.get("body") or "{}")
        except (json.JSONDecodeError, TypeError):
            return None
        source = decoded.get("data") if isinstance(decoded, dict) else None
        if not isinstance(source, dict):
            source = decoded if isinstance(decoded, dict) else {}
        listener_id = NotificationItem.optional_text(source.get("listenerId"))
        notification_id = NotificationItem.optional_text(source.get("notificationId"))
        try:
            schema_version = int(source.get("schemaVersion"))
        except (TypeError, ValueError):
            return None
        if (
            schema_version != NotificationConstants.SCHEMA_VERSION
            or not listener_id
            or not notification_id
        ):
            return None
        return {
            "schemaVersion": schema_version,
            "notificationId": notification_id,
            "listenerId": listener_id,
        }
