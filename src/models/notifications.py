from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Literal, Mapping

from config import settings
from src.models.notification_policy import NotificationPolicy
from src.services.logging_control import ApplicationLog
from src.utils.filters import SearchFilters
from src.utils.search_payload import SearchPayload


@dataclass(frozen=True, slots=True)
class NotificationOfferCommand:
    explicit: bool
    request_type: str
    listener_id: str
    api_enabled: bool


@dataclass(frozen=True, slots=True)
class NotificationOfferResult:
    kind: Literal["none", "unavailable", "failed", "empty", "offer"]
    item: dict | None = None
    remaining_count: int = 0


@dataclass(frozen=True, slots=True)
class NotificationAcceptCommand:
    listener_id: str
    alexa_user_id: str | None
    store: Mapping[str, object]
    item: Mapping[str, object]
    timeout_ms: int


@dataclass(frozen=True, slots=True)
class NotificationAcceptResult:
    kind: Literal["missing", "failed", "empty", "play"]
    payload: dict | None = None
    results: tuple[dict, ...] = ()


class Notification:
    """Framework-free notification workflow and Hear notification API owner."""

    __slots__ = ("_notification_api", "_heara")

    def __init__(self, notification_api, heara) -> None:
        self._notification_api = notification_api
        self._heara = heara

    async def update_status(
        self, *, listener_id: str, item: Mapping[str, object], status: str
    ) -> bool:
        notification_id = str(item.get("notificationId") or "").strip()
        if not listener_id or not notification_id:
            return False
        try:
            result = await self._notification_api.update(
                {
                    "listenerId": listener_id,
                    "notificationId": notification_id,
                    "status": status,
                }
            )
            return bool(result.get("updated"))
        except Exception as exc:
            ApplicationLog.warning(
                "Hear: notification status update failed status=%s error=%s",
                status,
                type(exc).__name__,
            )
            return False

    async def offer(self, command: NotificationOfferCommand) -> NotificationOfferResult:
        initial = NotificationPolicy.offer(
            explicit=command.explicit,
            request_type=command.request_type,
            listener_id=command.listener_id,
            api_enabled=command.api_enabled,
        )
        if initial.kind == "none":
            return NotificationOfferResult("none")
        if initial.kind == "unavailable":
            return NotificationOfferResult("unavailable")
        try:
            result = await self._notification_api.pending(
                {
                    "listenerId": command.listener_id,
                    "purpose": "inbox",
                    "limit": max(1, settings.HEAR_NOTIFICATION_LIMIT),
                }
            )
            if result.get("failed"):
                raise RuntimeError("notification API unavailable")
            items = list(result.get("items") or ())
        except Exception as exc:
            ApplicationLog.warning(
                "Hear: notification inbox read failed error=%s", type(exc).__name__
            )
            return NotificationOfferResult("failed")

        decision = NotificationPolicy.offer(
            explicit=command.explicit,
            request_type=command.request_type,
            listener_id=command.listener_id,
            api_enabled=True,
            has_items=bool(items),
        )
        if decision.kind == "empty":
            return NotificationOfferResult("empty")
        source_item = items[0]
        item = NotificationPolicy.dialog_item(source_item)
        await self.update_status(
            listener_id=command.listener_id, item=source_item, status="offered"
        )
        return NotificationOfferResult(
            "offer", item=deepcopy(item), remaining_count=max(0, len(items) - 1)
        )

    async def accept(self, command: NotificationAcceptCommand) -> NotificationAcceptResult:
        item = dict(command.item)
        if not item.get("notificationId"):
            return NotificationAcceptResult("missing")
        await self.update_status(
            listener_id=command.listener_id, item=item, status="resolving"
        )
        publication = item.get("publication")
        publication_id = (
            str(publication.get("id") or "").strip()
            if isinstance(publication, Mapping)
            else ""
        )
        filters = SearchFilters.source(
            "publication" if publication_id else str(item.get("sourceType") or ""),
            publication_id or item.get("sourceId"),
        )
        payload = SearchPayload.build(
            command.alexa_user_id,
            dict(command.store),
            q="",
            limit=10,
            page=0,
            sort="latest",
            nlp_filter=filters,
        )
        try:
            result = await self._heara.search(payload, timeout_ms=command.timeout_ms)
        except Exception as exc:
            ApplicationLog.warning(
                "Hear: notification content lookup failed error=%s", type(exc).__name__
            )
            result = {"failed": True}
        if result.get("failed"):
            await self.update_status(
                listener_id=command.listener_id, item=item, status="pending"
            )
            return NotificationAcceptResult("failed")
        results = tuple(
            deepcopy(entry)
            for entry in (result.get("results") or ())
            if isinstance(entry, dict)
        )
        if not results:
            await self.update_status(
                listener_id=command.listener_id, item=item, status="unavailable"
            )
            return NotificationAcceptResult("empty")
        return NotificationAcceptResult("play", payload=payload, results=results)
