from __future__ import annotations


class NotificationConstants:
    INTENTS = frozenset(
        {
            "HearNotificationsIntent",
            "EnableNotificationsIntent",
            "DisableNotificationsIntent",
        }
    )
    ACTIVE_INDEX = "ActiveByListener"
    ACTIVE_PARTITION_KEY = "activeListenerId"
    ACTIVE_SORT_KEY = "activePublishedAt"
    CONTENT = "content"
    PUBLICATION = "publication"
    ACTIVE_STATUSES = frozenset({"pending", "offered", "resolving", "queued"})
    TERMINAL_STATUSES = frozenset({"consumed", "dismissed", "unavailable"})
    DELIVERY_RETRYABLE_STATUSES = frozenset({429, 432, 500, 503})
    EVENT_NAME = "AMAZON.MediaContent.Available"
    LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
    LWA_SCOPE = "alexa::proactive_events"
    DEVELOPMENT_ENDPOINT = (
        "https://api.eu.amazonalexa.com/v1/proactiveEvents/stages/development"
    )
    PRODUCTION_ENDPOINT = "https://api.eu.amazonalexa.com/v1/proactiveEvents/"
    DEFAULT_LOCALE = "en-GB"
    DEFAULT_PROVIDER = "Hear"
    DELIVERY_EXPIRY_HOURS = 6
    SCHEMA_VERSION = 1
