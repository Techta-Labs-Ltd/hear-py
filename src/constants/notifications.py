from __future__ import annotations


class NotificationConstants:
    INTENTS = frozenset(
        {
            "HearNotificationsIntent",
            "EnableNotificationsIntent",
            "DisableNotificationsIntent",
        }
    )
    CREATOR_UPDATE = "creator_update"
    ORGANIZATION_UPDATE = "organization_update"
    ACTIVE_STATUSES = frozenset({"pending", "offered", "resolving", "queued"})
    TERMINAL_STATUSES = frozenset({"consumed", "dismissed", "unavailable"})
    DEFAULT_LOCALE = "en-GB"
    SCHEMA_VERSION = 1
