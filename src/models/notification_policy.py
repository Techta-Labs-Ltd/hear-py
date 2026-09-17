from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class NotificationOfferDecision:
    kind: Literal["none", "unavailable", "fetch", "empty", "offer"]


class NotificationPolicy:
    @staticmethod
    def offer(
        *,
        explicit: bool,
        request_type: str,
        listener_id: str,
        api_enabled: bool,
        has_items: bool | None = None,
    ) -> NotificationOfferDecision:
        if not explicit and request_type != "LaunchRequest":
            return NotificationOfferDecision("none")
        if not listener_id or not api_enabled:
            return NotificationOfferDecision("unavailable" if explicit else "none")
        if has_items is None:
            return NotificationOfferDecision("fetch")
        return NotificationOfferDecision("offer" if has_items else "empty")

    @staticmethod
    def dialog_item(item: dict) -> dict:
        allowed = {
            "notificationId",
            "notificationType",
            "sourceType",
            "sourceId",
            "sourceName",
            "lastDate",
            "expiresAt",
        }
        return {key: item[key] for key in allowed if item.get(key) is not None}
