from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from config import settings
from src.clients.availability import AvailabilityResponse
from src.clients.pool import HttpPool
from src.constants.discovery import DiscoveryConstants
from src.constants.search import SearchConstants
from src.services.logging_control import ApplicationLog
from src.utils.content_normalizer import ContentNormalizer
from src.utils.filters import SearchFilters
from src.utils.listener_payload import ListenerPayload
from src.utils.search_payload import SearchPayload


class HearApiSupport:
    ALLOWED_SORT_VALUES = SearchConstants.ALLOWED_SEARCH_SORTS
    _EMPTY_SEARCH_RESULT: dict[str, Any] = {
        "results": [],
        "total_hits": 0,
        "total_pages": 0,
        "page": 0,
        "client_message": None,
        "search_relaxation": None,
        "failed": True,
    }

@dataclass(frozen=True, slots=True)
class HearApiOptions:
    api_key: str | None = None
    base_url: str | None = None
    timeout_ms: int | None = None
    path_prefix: str | None = None
    retry_count: int | None = None
    page_limit: int | None = None


@dataclass(frozen=True, slots=True)
class HearHttpResponse:
    status: int
    data: dict | list | None
    retry_after_ms: int | None = None

    def __iter__(self):
        yield self.status
        yield self.data


@dataclass(frozen=True, slots=True)
class HearRequestIdentity:
    alexa_user_id: str | None = None
    listener_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "alexa_user_id", str(self.alexa_user_id or "").strip() or None)
        object.__setattr__(self, "listener_id", str(self.listener_id or "").strip() or None)


class ListenerBoundHearClient:
    """Immutable per-request identity view over reusable Hear infrastructure."""

    __slots__ = ("_client", "_identity")

    def __init__(self, client: "HearApiClient", identity: HearRequestIdentity) -> None:
        self._client = client
        self._identity = identity

    @property
    def identity(self) -> HearRequestIdentity:
        return self._identity

    def _with_identity(self, payload: dict | None) -> dict:
        bound = dict(payload or {})
        if self._identity.alexa_user_id:
            bound["alexaUserId"] = self._identity.alexa_user_id
        else:
            bound.pop("alexaUserId", None)
        if self._identity.listener_id:
            bound["listenerId"] = self._identity.listener_id
        else:
            bound.pop("listenerId", None)
        return bound

    async def search(self, payload: dict | None = None, timeout_ms: int | None = None) -> dict:
        return await self._client.search(self._with_identity(payload), timeout_ms=timeout_ms)

    async def availability(
        self, payload: dict | None = None, timeout_ms: int | None = None
    ) -> dict:
        return await self._client.availability(self._with_identity(payload), timeout_ms=timeout_ms)


class HearApiClient:
    __slots__ = (
        "_api_key",
        "_base_url",
        "_timeout_ms",
        "_path_prefix",
        "_retry_count",
        "_page_limit",
        "_pool",
    )

    def __init__(
        self, options: HearApiOptions | None = None, *, pool: HttpPool | None = None
    ) -> None:
        configured = options or HearApiOptions()
        self._api_key = configured.api_key or settings.api_key
        self._base_url = (configured.base_url or settings.api_base_url).rstrip("/")
        self._timeout_ms = (
            configured.timeout_ms if configured.timeout_ms is not None else settings.api_timeout_ms
        )
        self._path_prefix = (
            configured.path_prefix
            if configured.path_prefix is not None
            else getattr(settings, "HEAR_API_PATH_PREFIX", "") or ""
        ).strip("/")
        self._retry_count = (
            configured.retry_count
            if configured.retry_count is not None
            else settings.api_retry_count
        )
        self._page_limit = (
            configured.page_limit
            if configured.page_limit is not None
            else settings.search_page_limit
        )
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

    def bind(self, identity: HearRequestIdentity) -> ListenerBoundHearClient:
        return ListenerBoundHearClient(self, identity)

    async def _raw_request(
        self,
        method: str,
        path: str,
        json_data: dict | None = None,
        timeout_ms: int | None = None,
    ) -> HearHttpResponse:
        resolved_timeout_ms = (
            timeout_ms or self._timeout_ms or settings.HEAR_HTTP_DEFAULT_TIMEOUT_MS
        )
        timeout = httpx.Timeout(max(resolved_timeout_ms, 1) / 1000.0)
        try:
            client = self._pool.get()
            response = await client.request(
                method, self._build_api_path(path), json=json_data, timeout=timeout
            )
            if not 200 <= response.status_code < 300:
                ApplicationLog.warning(
                    "Hear API request failed method=%s path=%s status=%s",
                    method,
                    self._build_api_path(path),
                    response.status_code,
                )
                return HearHttpResponse(
                    response.status_code,
                    None,
                    self._parse_retry_after_ms(response.headers.get("Retry-After")),
                )
            if not response.content:
                return HearHttpResponse(response.status_code, None)
            try:
                return HearHttpResponse(response.status_code, response.json())
            except ValueError:
                return HearHttpResponse(response.status_code, None)
        except Exception as exc:
            ApplicationLog.warning(
                "Hear API request error method=%s path=%s error=%s",
                method,
                self._build_api_path(path),
                type(exc).__name__,
            )
            return HearHttpResponse(0, None)

    def _build_api_path(self, relative: str) -> str:
        rel = relative.lstrip("/")
        return f"/{self._path_prefix}/{rel}" if self._path_prefix else f"/{rel}"

    def _build_alexa_relative_path(self, relative: str) -> str:
        if self._path_prefix:
            return f"/{relative.strip('/')}"
        return f"/alexa/{relative.strip('/')}"

    def _build_alexa_search_path(self) -> str:
        return self._build_alexa_relative_path("search")

    def _build_alexa_availability_path(self) -> str:
        return self._build_alexa_relative_path("availability")

    @staticmethod
    def _is_retryable(status: int) -> bool:
        return status == 0 or status == 429 or status >= 500

    @staticmethod
    def _parse_retry_after_ms(value: str | None) -> int | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            seconds = float(text)
            if math.isfinite(seconds) and seconds >= 0:
                return math.ceil(seconds * 1000)
        except ValueError:
            pass
        try:
            retry_at = parsedate_to_datetime(text)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0, math.ceil((retry_at - datetime.now(timezone.utc)).total_seconds() * 1000))
        except (TypeError, ValueError, IndexError, OverflowError):
            return None

    def _retry_deadline(self, timeout_ms: int | None) -> float:
        budget_ms = timeout_ms or self._timeout_ms or settings.HEAR_HTTP_DEFAULT_TIMEOUT_MS
        return asyncio.get_running_loop().time() + max(int(budget_ms), 1) / 1000.0

    def _retry_delay_seconds(self, response, attempt: int) -> float:
        retry_after_ms = getattr(response, "retry_after_ms", None)
        if isinstance(retry_after_ms, int) and retry_after_ms >= 0:
            return retry_after_ms / 1000.0
        return settings.HEAR_API_RETRY_BACKOFF_MS / 1000.0 * 2**attempt

    async def _wait_to_retry(self, response, attempt: int, deadline: float) -> bool:
        delay_seconds = self._retry_delay_seconds(response, attempt)
        remaining_seconds = deadline - asyncio.get_running_loop().time()
        if delay_seconds >= remaining_seconds:
            ApplicationLog.warning(
                "Hear API retry skipped attempt=%s retryDelayMs=%s remainingMs=%s",
                attempt + 1,
                math.ceil(delay_seconds * 1000),
                max(0, math.floor(remaining_seconds * 1000)),
            )
            return False
        await asyncio.sleep(delay_seconds)
        return True

    @staticmethod
    def _normalize_search_response(data: dict, search_payload: dict | None = None) -> dict:
        raw_results = data.get("results") or data.get("items") or []
        publication_choices = ContentNormalizer.publication_choices(raw_results)
        contextualized = ContentNormalizer.apply_search_context(
            raw_results,
            search_payload,
            data,
        )
        results = ContentNormalizer.normalize_content_items(contextualized)
        return {
            "results": results,
            "total_hits": data.get("total")
            if isinstance(data.get("total"), (int, float))
            else len(results),
            "total_pages": data.get("totalPages")
            if isinstance(data.get("totalPages"), (int, float))
            else None,
            "page": data.get("page") if isinstance(data.get("page"), (int, float)) else 0,
            "client_message": data.get("client_message")
            if data.get("client_message") is not None
            else None,
            "search_relaxation": data.get("search_relaxation")
            if data.get("search_relaxation") is not None
            else None,
            "session_key": data.get("session_key")
            if isinstance(data.get("session_key"), str) and data.get("session_key")
            else None,
            "_publication_choices": publication_choices,
        }

    async def search(self, payload: dict | None = None, timeout_ms: int | None = None) -> dict:
        payload = SearchPayload.with_pagination(payload, self._page_limit)
        query = payload["query"]
        body: dict[str, Any] = {
            "query": query,
            "limit": payload["limit"],
            "page": payload["page"],
        }
        for key in SearchConstants.SEARCH_API_FIELDS:
            if payload.get(key) is not None:
                body[key] = payload[key]
        filters = {
            key: value
            for key, value in dict(body.get("filter") or {}).items()
            # Search booleans are opt-in.  Keep this at the wire boundary as a
            # safeguard for callers which build a payload without SearchPayload.
            if not (key in {"isPublication", "isLocal"} and value is False)
        }
        for key in SearchConstants.SEARCH_DATE_FILTER_KEYS:
            if key not in filters and payload.get(key) is not None:
                filters[key] = payload[key]
        if filters:
            body["filter"] = filters
        else:
            body.pop("filter", None)
        if payload.get("sort") in HearApiSupport.ALLOWED_SORT_VALUES:
            body["sort"] = payload["sort"]
        path = self._build_alexa_search_path()
        ApplicationLog.info(
            "Hear API search request path=%s queryPresent=%s limit=%s page=%s filterKeys=%s alexaUserIdPresent=%s listenerIdPresent=%s",
            path,
            bool(body.get("query")),
            body["limit"],
            body["page"],
            sorted((body.get("filter") or {}).keys()),
            bool(body.get("alexaUserId")),
            bool(body.get("listenerId")),
        )
        deadline = self._retry_deadline(timeout_ms)
        for attempt in range(self._retry_count + 1):
            response = await self._raw_request("POST", path, body, timeout_ms)
            status, data = response
            ApplicationLog.info(
                "Hear API search response attempt=%s status=%s", attempt + 1, status
            )
            if status == 200 and isinstance(data, dict):
                return {
                    **self._normalize_search_response(data, body),
                    "failed": False,
                    "_search_payload": dict(body),
                }
            if attempt < self._retry_count and self._is_retryable(status):
                if not await self._wait_to_retry(response, attempt, deadline):
                    break
            else:
                break
        return dict(HearApiSupport._EMPTY_SEARCH_RESULT)

    async def availability(
        self, payload: dict | None = None, timeout_ms: int | None = None
    ) -> dict:
        requested = payload if isinstance(payload, dict) else {}
        availability_filter = SearchFilters.availability(requested.get("filter"))
        alexa_user_id = str(requested.get("alexaUserId") or "").strip()
        listener_id = str(requested.get("listenerId") or "").strip()
        is_recommended = bool(requested.get("isRecommended"))
        body = {
            "filter": availability_filter or {},
            "page": AvailabilityResponse.integer(requested.get("page")),
            "limit": AvailabilityResponse.integer(
                requested.get("limit"), DiscoveryConstants.CHOICE_PAGE_SIZE, 1
            ),
        }
        if alexa_user_id:
            body["alexaUserId"] = alexa_user_id
        if listener_id:
            body["listenerId"] = listener_id
        if is_recommended:
            body["isRecommended"] = True
        if availability_filter and "location" not in availability_filter:
            body["isLocal"] = bool(requested.get("isLocal"))
        if (availability_filter is None and not is_recommended) or not (
            listener_id or alexa_user_id
        ):
            supplied_filter = requested.get("filter")
            ApplicationLog.warning(
                "Hear API availability request rejected invalid filterKeys=%s alexaUserIdPresent=%s listenerIdPresent=%s",
                sorted(supplied_filter.keys()) if isinstance(supplied_filter, dict) else [],
                bool(alexa_user_id),
                bool(listener_id),
            )
            return AvailabilityResponse.failed(body)
        path = self._build_alexa_availability_path()
        ApplicationLog.info(
            "Hear API availability request path=%s page=%s limit=%s filterKeys=%s isLocal=%s",
            path,
            body["page"],
            body["limit"],
            sorted(filter_body.keys()) if isinstance((filter_body := body.get("filter")), dict) else [],
            body.get("isLocal", "omitted"),
        )
        deadline = self._retry_deadline(timeout_ms)
        for attempt in range(self._retry_count + 1):
            response = await self._raw_request("POST", path, body, timeout_ms)
            status, data = response
            ApplicationLog.info(
                "Hear API availability response attempt=%s status=%s", attempt + 1, status
            )
            if status == 200 and isinstance(data, dict):
                ApplicationLog.info("Hear API availability response bodyPresent=true")
                return AvailabilityResponse.normalize(data, body)
            if attempt < self._retry_count and self._is_retryable(status):
                if not await self._wait_to_retry(response, attempt, deadline):
                    break
            else:
                break
        return AvailabilityResponse.failed(body)

    async def resolve_listener_identity(
        self,
        identity: dict,
        *,
        timeout_ms: int | None = None,
    ) -> dict | None:
        body = ListenerPayload.resolution(identity)
        if not body:
            return None
        status, data = await self._raw_request(
            "POST",
            self._build_alexa_relative_path("listeners/resolve"),
            body,
            timeout_ms,
        )
        return data if status == 200 and isinstance(data, dict) else None

    async def sync_listener(self, profile: dict, *, timeout_ms: int | None = None) -> dict | None:
        body = ListenerPayload.registration(profile)
        if not body:
            return None
        status, data = await self._raw_request(
            "POST",
            self._build_alexa_relative_path("listeners/sync"),
            body,
            timeout_ms,
        )
        return data if status == 200 and isinstance(data, dict) else None

    async def register_listener(
        self, profile: dict, *, timeout_ms: int | None = None
    ) -> dict | None:
        body = ListenerPayload.registration(profile)
        if not body:
            return None
        status, data = await self._raw_request(
            "POST",
            self._build_alexa_relative_path("listeners/register"),
            body,
            timeout_ms,
        )
        return data if status == 200 and isinstance(data, dict) else None
