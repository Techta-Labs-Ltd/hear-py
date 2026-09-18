from __future__ import annotations

import asyncio

from config import settings
from src.services.logging_control import ApplicationLog
from src.utils.deadline import RequestDeadline
from src.utils.events import SqsBatch
from src.utils.notifications import NotificationQueueMessage


class NotificationDeliveryService:
    """Consume one SQS batch with one backend fetch and one backend status update."""

    __slots__ = ("_notification_api", "_proactive", "_recipients", "_send_concurrency")

    def __init__(self, notification_api, proactive, recipients=None, *, send_concurrency: int | None = None) -> None:
        self._notification_api = notification_api
        self._proactive = proactive
        self._recipients = recipients
        self._send_concurrency = max(
            1,
            send_concurrency
            if send_concurrency is not None
            else settings.HEAR_PROACTIVE_SEND_CONCURRENCY,
        )

    async def consume(
        self, records: list[dict], *, deadline: RequestDeadline | None = None
    ) -> dict:
        message_ids = SqsBatch.message_ids(records)
        budget = deadline if deadline is not None else RequestDeadline.from_context(None)
        by_key: dict[tuple[str, str], list[str]] = {}
        failures: set[str] = set()
        for record, message_id in zip(records, message_ids):
            message = NotificationQueueMessage.decode(record)
            if message is None:
                ApplicationLog.warning("Hear: invalid notification queue record")
                failures.add(message_id)
                continue
            key = message["listenerId"], message["notificationId"]
            by_key.setdefault(key, []).append(message_id)

        keys = list(by_key)
        for start in range(0, len(keys), 100):
            failures.update(
                await self._consume_chunk(
                    keys[start : start + 100],
                    by_key,
                    budget,
                )
            )
        return {"batchItemFailures": [{"itemIdentifier": message_id} for message_id in message_ids if message_id in failures]}

    async def _consume_chunk(
        self,
        keys: list[tuple[str, str]],
        message_ids_by_key: dict[tuple[str, str], list[str]],
        budget: RequestDeadline,
    ) -> set[str]:
        requests = [{"listenerId": listener_id, "notificationId": notification_id} for listener_id, notification_id in keys]
        fetch = await self._call_with_budget(
            self._notification_api.pending_batch(requests, timeout_ms=self._remaining_ms(budget)),
            budget,
        )
        if not isinstance(fetch, dict) or fetch.get("failed"):
            return self._message_ids(keys, message_ids_by_key)
        decisions = {
            (str(item.get("listenerId") or ""), str(item.get("notificationId") or "")): item
            for item in fetch.get("items") or []
            if isinstance(item, dict)
        }
        if set(decisions) != set(keys):
            ApplicationLog.warning("Hear: notification batch response did not match request")
            return self._message_ids(keys, message_ids_by_key)

        eligible = [item for item in decisions.values() if item.get("deliverable") is True]
        try:
            recipients = await self._call_with_budget(
                self._recipients.get_many([item["listenerId"] for item in eligible])
                if self._recipients is not None
                else self._missing_recipients(),
                budget,
            )
        except Exception as exc:
            ApplicationLog.warning(
                "Hear: notification recipient batch lookup failed error=%s",
                type(exc).__name__,
            )
            return self._message_ids(keys, message_ids_by_key)

        outcomes: dict[tuple[str, str], dict] = {}
        to_send: list[dict] = []
        for item in eligible:
            key = item["listenerId"], item["notificationId"]
            recipient = self._recipient_id(recipients.get(item["listenerId"])) if isinstance(recipients, dict) else None
            if recipient is None:
                outcomes[key] = self._outcome(item, "failed", error_code="recipient_not_currently_mapped")
            elif not item.get("sendProactive", True):
                outcomes[key] = self._outcome(item, "suppressed", error_code="send_proactive_disabled")
            else:
                to_send.append({**item, "alexaUserId": recipient})

        try:
            outcomes.update(await self._deliver_bounded(to_send, budget))
        except Exception as exc:
            ApplicationLog.warning("Hear: proactive delivery batch failed error=%s", type(exc).__name__)
            return self._message_ids(keys, message_ids_by_key)

        if not outcomes:
            return set()
        update = await self._call_with_budget(
            self._notification_api.update_batch(list(outcomes.values()), timeout_ms=self._remaining_ms(budget)),
            budget,
        )
        if not isinstance(update, dict) or update.get("failed"):
            return self._message_ids(list(outcomes), message_ids_by_key)
        updated = {
            (str(item.get("listenerId") or ""), str(item.get("notificationId") or "")): bool(item.get("updated"))
            for item in update.get("items") or []
            if isinstance(item, dict)
        }
        failures: set[str] = set()
        for key, outcome in outcomes.items():
            if not updated.get(key) or outcome["retryable"]:
                failures.update(message_ids_by_key[key])
        return failures

    async def _deliver_bounded(
        self, items: list[dict], budget: RequestDeadline
    ) -> dict[tuple[str, str], dict]:
        semaphore = asyncio.Semaphore(self._send_concurrency)

        async def deliver(item: dict) -> tuple[tuple[str, str], dict]:
            async with semaphore:
                result = await self._call_with_budget(self._proactive.deliver(item), budget)
            key = item["listenerId"], item["notificationId"]
            if result.get("sent"):
                ApplicationLog.info("Hear: proactive notification delivered")
                return key, self._outcome(item, "sent", http_status=result.get("httpStatus"))
            retryable = bool(result.get("retryable"))
            return key, self._outcome(
                item,
                "retrying" if retryable else "failed",
                http_status=result.get("httpStatus"),
                error_code=result.get("errorCode"),
                retryable=retryable,
            )

        return dict(await asyncio.gather(*(deliver(item) for item in items)))

    @staticmethod
    def _outcome(
        item: dict,
        status: str,
        *,
        http_status: int | None = None,
        error_code: str | None = None,
        retryable: bool = False,
    ) -> dict:
        outcome = {
            "listenerId": item["listenerId"],
            "notificationId": item["notificationId"],
            "deliveryStatus": status,
            "retryable": retryable,
        }
        if http_status is not None:
            outcome["deliveryHttpStatus"] = http_status
        if error_code:
            outcome["deliveryErrorCode"] = str(error_code)[:120]
        return outcome

    @staticmethod
    def _recipient_id(recipient: object) -> str | None:
        if not isinstance(recipient, dict):
            return None
        value = str(recipient.get("alexaUserId") or "").strip()
        return value or None

    @staticmethod
    async def _missing_recipients() -> dict:
        return {}

    @staticmethod
    def _message_ids(
        keys: list[tuple[str, str]], message_ids_by_key: dict[tuple[str, str], list[str]]
    ) -> set[str]:
        return {message_id for key in keys for message_id in message_ids_by_key[key]}

    @staticmethod
    def _remaining_ms(budget: RequestDeadline) -> int:
        return max(1, budget.remaining_ms(500))

    async def _call_with_budget(self, awaitable, budget: RequestDeadline):
        remaining_ms = budget.remaining_ms(500)
        if remaining_ms <= 0:
            raise TimeoutError("notification Lambda deadline exhausted")
        return await asyncio.wait_for(awaitable, timeout=remaining_ms / 1000.0)
