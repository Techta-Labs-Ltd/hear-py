from __future__ import annotations

from src.constants.notifications import NotificationConstants


class NotificationInboxItem:
    __slots__ = ()

    @staticmethod
    def normalize(item: dict | None) -> dict | None:
        source = item if isinstance(item, dict) else {}
        listener_id = str(source.get("listenerId") or "").strip()
        notification_id = str(source.get("notificationId") or "").strip()
        notification_type = str(source.get("notificationType") or "").strip().casefold()
        content_id = str(source.get("contentId") or "").strip() or None
        publication_id = str(source.get("publicationId") or "").strip() or None
        if (
            not listener_id
            or not notification_id
            or notification_type
            not in {NotificationConstants.CONTENT, NotificationConstants.PUBLICATION}
        ):
            return None
        if notification_type == NotificationConstants.CONTENT and (
            not content_id or publication_id
        ):
            return None
        if notification_type == NotificationConstants.PUBLICATION and (
            not publication_id or content_id
        ):
            return None
        return {
            key: value
            for key, value in {
                "schemaVersion": int(
                    source.get("schemaVersion") or NotificationConstants.SCHEMA_VERSION
                ),
                "listenerId": listener_id,
                "notificationId": notification_id,
                "notificationType": notification_type,
                "contentId": content_id,
                "publicationId": publication_id,
                "title": NotificationInboxItem.optional_text(source.get("title")),
                "creatorId": NotificationInboxItem.optional_text(source.get("creatorId")),
                "creatorName": NotificationInboxItem.optional_text(source.get("creatorName")),
                "organizationId": NotificationInboxItem.optional_text(
                    source.get("organizationId")
                ),
                "organizationName": NotificationInboxItem.optional_text(
                    source.get("organizationName")
                ),
                "alexaUserId": NotificationInboxItem.optional_text(
                    source.get("alexaUserId")
                ),
                "locale": NotificationInboxItem.optional_text(source.get("locale"))
                or NotificationConstants.DEFAULT_LOCALE,
                "publishedAt": NotificationInboxItem.integer(source.get("publishedAt")),
                "status": NotificationInboxItem.optional_text(source.get("status"))
                or "pending",
                "deliveryStatus": NotificationInboxItem.optional_text(
                    source.get("deliveryStatus")
                )
                or "pending",
                "sendProactive": source.get("sendProactive") is not False,
                "expiresAt": NotificationInboxItem.integer(source.get("expiresAt")),
            }.items()
            if value is not None
        }

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
    def active_sort_key(item: dict) -> str:
        published_at = max(0, int(item.get("publishedAt") or 0))
        return f"{published_at:020d}#{item['notificationId']}"


class NotificationStreamDecoder:
    __slots__ = ()

    @staticmethod
    def value(attribute: dict | None):
        if not isinstance(attribute, dict):
            return None
        if "NULL" in attribute:
            return None
        if "S" in attribute:
            return attribute["S"]
        if "N" in attribute:
            number = str(attribute["N"])
            return float(number) if "." in number else int(number)
        if "BOOL" in attribute:
            return bool(attribute["BOOL"])
        if "L" in attribute:
            return [NotificationStreamDecoder.value(value) for value in attribute["L"]]
        if "M" in attribute:
            return {
                key: NotificationStreamDecoder.value(value)
                for key, value in attribute["M"].items()
            }
        return None

    @staticmethod
    def item(raw: dict) -> dict:
        return {
            key: NotificationStreamDecoder.value(value)
            for key, value in (raw or {}).items()
        }
