from __future__ import annotations

import httpx

from config import settings
from src.clients.pool import HttpPool
from src.services.logging_control import ApplicationLog
from src.utils.notifications import NotificationItem


class NotificationApiClient:
    __slots__ = ("_api_key", "_base_url", "_path", "_pool", "_timeout_ms")

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        path_prefix: str | None = None,
        timeout_ms: int | None = None,
        pool: HttpPool | None = None,
    ) -> None:
        self._api_key = settings.api_key if api_key is None else api_key
        self._base_url = (settings.api_base_url if base_url is None else base_url).rstrip("/")
        prefix = (settings.HEAR_API_PATH_PREFIX if path_prefix is None else path_prefix).strip("/")
        self._path = f"/{prefix}/notification" if prefix else "/alexa/notification"
        self._timeout_ms = timeout_ms or settings.api_timeout_ms
        self._pool = (
            pool
            if pool is not None
            else HttpPool(
                base_url=self._base_url,
                headers={"X-Api-Key": self._api_key},
                timeout_ms=max(self._timeout_ms or 30000, 1),
            )
        )
        self._pool.assert_configuration(
            base_url=self._base_url, headers={"X-Api-Key": self._api_key}
        )

    @property
    def enabled(self) -> bool:
        return bool(self._base_url and self._api_key)

    async def _post(self, body: dict, timeout_ms: int | None = None) -> tuple[int, dict | None]:
        timeout = httpx.Timeout(
            max(timeout_ms or self._timeout_ms or settings.HEAR_HTTP_DEFAULT_TIMEOUT_MS, 1) / 1000.0
        )
        try:
            response = await self._pool.get().post(self._path, json=body, timeout=timeout)
        except Exception as exc:
            ApplicationLog.warning(
                "Hear: notification API request failed error=%s",
                type(exc).__name__,
            )
            return (0, None)
        if not 200 <= response.status_code < 300:
            ApplicationLog.warning(
                "Hear: notification API rejected operation=%s status=%s",
                body.get("operation"),
                response.status_code,
            )
            return (response.status_code, None)
        if not response.content:
            return (response.status_code, None)
        try:
            data = response.json()
        except ValueError:
            return (response.status_code, None)
        return (response.status_code, data if isinstance(data, dict) else None)

    async def pending(
        self,
        request: dict,
        *,
        timeout_ms: int | None = None,
    ) -> dict:
        requested = request if isinstance(request, dict) else {}
        body = {
            key: value
            for key, value in {
                "operation": "fetch",
                "listenerId": str(requested.get("listenerId") or "").strip(),
                "notificationId": str(requested.get("notificationId") or "").strip() or None,
                "purpose": str(requested.get("purpose") or "inbox").strip().casefold(),
                "limit": max(1, int(requested.get("limit") or 5)),
            }.items()
            if value is not None
        }
        if not body["listenerId"]:
            return {"items": [], "failed": True, "retryable": False, "httpStatus": 0}
        status, data = await self._post(body, timeout_ms)
        if status in {204, 404, 409}:
            return {"items": [], "failed": False, "retryable": False, "httpStatus": status}
        if status == 200 and isinstance(data, dict):
            raw_items = NotificationItem.response_items(data)
            items = [
                normalized
                for item in raw_items
                if (normalized := NotificationItem.normalize(item))
                and NotificationItem.matches_request(normalized, body)
            ]
            if raw_items and not items:
                return {"items": [], "failed": True, "retryable": True, "httpStatus": status}
            limit_value = body.get("limit")
            limit = int(limit_value) if isinstance(limit_value, int) else len(items)
            return {
                "items": items[:limit],
                "failed": False,
                "retryable": False,
                "httpStatus": status,
            }
        return {
            "items": [],
            "failed": True,
            "retryable": status == 0 or status == 429 or status >= 500,
            "httpStatus": status,
        }

    async def update(
        self,
        request: dict,
        *,
        timeout_ms: int | None = None,
    ) -> dict:
        requested = request if isinstance(request, dict) else {}
        body = {
            key: value
            for key, value in {
                "operation": "update",
                "listenerId": str(requested.get("listenerId") or "").strip(),
                "notificationId": str(requested.get("notificationId") or "").strip(),
                "status": str(requested.get("status") or "").strip().casefold() or None,
                "deliveryStatus": (
                    str(requested.get("deliveryStatus") or "").strip().casefold() or None
                ),
                "deliveryHttpStatus": requested.get("deliveryHttpStatus"),
                "deliveryErrorCode": (
                    str(requested.get("deliveryErrorCode") or "").strip()[:120] or None
                ),
            }.items()
            if value is not None
        }
        if not body["listenerId"] or not body["notificationId"]:
            return {"updated": False, "retryable": False, "httpStatus": 0}
        response_status, _ = await self._post(body, timeout_ms)
        return {
            "updated": 200 <= response_status < 300,
            "retryable": (response_status == 0 or response_status == 429 or response_status >= 500),
            "httpStatus": response_status,
        }

    async def pending_batch(
        self,
        requests: list[dict],
        *,
        timeout_ms: int | None = None,
    ) -> dict:
        items = self._batch_items(requests, delivery=True)
        if not items:
            return {"items": [], "failed": True, "retryable": False, "httpStatus": 0}
        status, data = await self._post(
            {"operation": "fetch_batch", "purpose": "delivery", "items": items},
            timeout_ms,
        )
        if status == 200 and isinstance(data, dict):
            raw_items = NotificationItem.response_items(data)
            requested = {
                (item["listenerId"], item["notificationId"])
                for item in items
            }
            results: dict[tuple[str, str], dict] = {}
            for raw in raw_items:
                listener_id = str(raw.get("listenerId") or "").strip()
                notification_candidate = raw.get("notification")
                notification: dict = (
                    notification_candidate
                    if isinstance(notification_candidate, dict)
                    else raw
                )
                notification_id = str(notification.get("notificationId") or "").strip()
                key = listener_id, notification_id
                if key not in requested or key in results:
                    return self._failed_batch(status, retryable=True)
                if raw.get("deliverable") is False:
                    results[key] = {"listenerId": listener_id, "notificationId": notification_id, "deliverable": False}
                    continue
                normalized = NotificationItem.normalize(raw)
                if normalized is None:
                    return self._failed_batch(status, retryable=True)
                results[key] = {"deliverable": True, **normalized}
            if set(results) != requested:
                return self._failed_batch(status, retryable=True)
            return {
                "items": [results[(item["listenerId"], item["notificationId"])] for item in items],
                "failed": False,
                "retryable": False,
                "httpStatus": status,
            }
        return self._failed_batch(status)

    async def update_batch(
        self,
        requests: list[dict],
        *,
        timeout_ms: int | None = None,
    ) -> dict:
        items = self._batch_items(requests, delivery=False)
        if not items:
            return {"items": [], "failed": True, "retryable": False, "httpStatus": 0}
        status, data = await self._post({"operation": "update_batch", "items": items}, timeout_ms)
        if status == 200 and isinstance(data, dict):
            raw_items = data.get("items")
            if not isinstance(raw_items, list):
                return self._failed_batch(status, retryable=True)
            requested = {(item["listenerId"], item["notificationId"]) for item in items}
            results: dict[tuple[str, str], bool] = {}
            for raw in raw_items:
                if not isinstance(raw, dict):
                    return self._failed_batch(status, retryable=True)
                key = str(raw.get("listenerId") or "").strip(), str(raw.get("notificationId") or "").strip()
                if key not in requested or key in results:
                    return self._failed_batch(status, retryable=True)
                results[key] = bool(raw.get("updated"))
            if set(results) != requested:
                return self._failed_batch(status, retryable=True)
            return {
                "items": [
                    {"listenerId": item["listenerId"], "notificationId": item["notificationId"], "updated": results[(item["listenerId"], item["notificationId"])]}
                    for item in items
                ],
                "failed": False,
                "retryable": False,
                "httpStatus": status,
            }
        return self._failed_batch(status)

    @staticmethod
    def _failed_batch(status: int, *, retryable: bool | None = None) -> dict:
        return {
            "items": [],
            "failed": True,
            "retryable": (
                status == 0 or status == 429 or status >= 500
                if retryable is None
                else retryable
            ),
            "httpStatus": status,
        }

    @staticmethod
    def _batch_items(requests: list[dict], *, delivery: bool) -> list[dict]:
        items: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for request in requests or []:
            if not isinstance(request, dict):
                continue
            listener_id = str(request.get("listenerId") or "").strip()
            notification_id = str(request.get("notificationId") or "").strip()
            key = listener_id, notification_id
            if not listener_id or not notification_id or key in seen:
                continue
            seen.add(key)
            item = {"listenerId": listener_id, "notificationId": notification_id}
            if not delivery:
                for name in ("status", "deliveryStatus", "deliveryHttpStatus", "deliveryErrorCode"):
                    value = request.get(name)
                    if value is not None:
                        item[name] = value
            items.append(item)
            if len(items) == 100:
                break
        return items
