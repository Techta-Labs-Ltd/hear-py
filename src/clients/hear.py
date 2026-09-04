from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from config import settings
from src.clients.availability import AvailabilityResponse
from src.clients.pool import HttpPool
from src.constants.discovery import DiscoveryConstants
from src.constants.search import SearchConstants
from src.utils.content_normalizer import ContentNormalizer
from src.utils.search_payload import SearchPayload


class HearApiSupport:
    logger = logging.getLogger(__name__)
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

    @staticmethod
    def _hash_text(text: str) -> str:
        if not text:
            return ""
        return f"{len(text):d}:{HearApiSupport._simple_hash(text)}"

    @staticmethod
    def _simple_hash(text: str) -> int:
        value = 0
        for char in text:
            value = value * 31 + ord(char) & 2147483647
        return value


@dataclass(frozen=True, slots=True)
class HearApiOptions:
    api_key: str | None = None
    base_url: str | None = None
    timeout_ms: int | None = None
    path_prefix: str | None = None
    retry_count: int | None = None
    page_limit: int | None = None


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
        self._pool = pool or HttpPool(timeout_ms=max(self._timeout_ms or 30000, 1))

    async def _raw_request(
        self,
        method: str,
        path: str,
        json_data: dict | None = None,
        timeout_ms: int | None = None,
    ) -> tuple[int, dict | list | None]:
        resolved_timeout_ms = (
            timeout_ms or self._timeout_ms or settings.HEAR_HTTP_DEFAULT_TIMEOUT_MS
        )
        timeout = httpx.Timeout(max(resolved_timeout_ms, 1) / 1000.0)
        try:
            client = self._pool.get(base_url=self._base_url, headers={"X-Api-Key": self._api_key})
            response = await client.request(
                method, self._build_api_path(path), json=json_data, timeout=timeout
            )
            if not 200 <= response.status_code < 300:
                HearApiSupport.logger.warning(
                    "Hear API request failed method=%s path=%s status=%s",
                    method,
                    self._build_api_path(path),
                    response.status_code,
                )
                return (response.status_code, None)
            return (response.status_code, response.json())
        except Exception as exc:
            HearApiSupport.logger.warning(
                "Hear API request error method=%s path=%s error=%s",
                method,
                self._build_api_path(path),
                type(exc).__name__,
            )
            return (0, None)

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
        return status >= 500

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
        filters = dict(body.get("filter") or {})
        for key in SearchConstants.SEARCH_DATE_FILTER_KEYS:
            if key not in filters and payload.get(key) is not None:
                filters[key] = payload[key]
        if filters:
            body["filter"] = filters
        if payload.get("sort") in HearApiSupport.ALLOWED_SORT_VALUES:
            body["sort"] = payload["sort"]
        path = self._build_alexa_search_path()
        query_text = body.get("query") or ""
        HearApiSupport.logger.info(
            "Hear API search request path=%s queryHash=%s queryChars=%s limit=%s page=%s filterKeys=%s alexaUserIdPresent=%s listenerIdPresent=%s",
            path,
            HearApiSupport._hash_text(str(query_text)),
            len(str(query_text)),
            body["limit"],
            body["page"],
            sorted((body.get("filter") or {}).keys()),
            bool(body.get("alexaUserId")),
            bool(body.get("listenerId")),
        )
        for attempt in range(self._retry_count + 1):
            status, data = await self._raw_request("POST", path, body, timeout_ms)
            HearApiSupport.logger.info(
                "Hear API search response attempt=%s status=%s", attempt + 1, status
            )
            if status == 200 and isinstance(data, dict):
                return {
                    **self._normalize_search_response(data, body),
                    "failed": False,
                    "_search_payload": dict(body),
                }
            if attempt < self._retry_count and self._is_retryable(status):
                await asyncio.sleep(settings.HEAR_API_RETRY_BACKOFF_MS / 1000.0 * 2**attempt)
            else:
                break
        return dict(HearApiSupport._EMPTY_SEARCH_RESULT)

    async def availability(
        self, payload: dict | None = None, timeout_ms: int | None = None
    ) -> dict:
        requested = payload if isinstance(payload, dict) else {}
        availability_filter = AvailabilityResponse.normalize_filter(requested.get("filter"))
        body = {
            "filter": availability_filter or {},
            "page": AvailabilityResponse.integer(requested.get("page")),
            "limit": AvailabilityResponse.integer(
                requested.get("limit"), DiscoveryConstants.CHOICE_PAGE_SIZE, 1
            ),
        }
        if availability_filter is None:
            supplied_filter = requested.get("filter")
            HearApiSupport.logger.warning(
                "Hear API availability request rejected invalid filterKeys=%s",
                sorted(supplied_filter.keys()) if isinstance(supplied_filter, dict) else [],
            )
            return AvailabilityResponse.failed(body)
        path = self._build_alexa_availability_path()
        HearApiSupport.logger.info(
            "Hear API availability request path=%s page=%s limit=%s filterKeys=%s",
            path,
            body["page"],
            body["limit"],
            sorted(body["filter"].keys()),
        )
        for attempt in range(self._retry_count + 1):
            status, data = await self._raw_request("POST", path, body, timeout_ms)
            HearApiSupport.logger.info(
                "Hear API availability response attempt=%s status=%s", attempt + 1, status
            )
            if status == 200 and isinstance(data, dict):
                return AvailabilityResponse.normalize(data, body)
            if attempt < self._retry_count and self._is_retryable(status):
                await asyncio.sleep(settings.HEAR_API_RETRY_BACKOFF_MS / 1000.0 * 2**attempt)
            else:
                break
        return AvailabilityResponse.failed(body)

    async def resolve_listener_identity(
        self,
        identity: dict,
        *,
        timeout_ms: int | None = None,
    ) -> dict | None:
        if not isinstance(identity, dict) or not identity.get("alexaUserId"):
            return None
        status, data = await self._raw_request(
            "POST",
            self._build_alexa_relative_path("listeners/resolve"),
            identity,
            timeout_ms,
        )
        return data if status == 200 and isinstance(data, dict) else None

    async def sync_listener(self, profile: dict, *, timeout_ms: int | None = None) -> dict | None:
        alexa_user_id = profile.get("alexaUserId") if isinstance(profile, dict) else None
        if not alexa_user_id:
            return None
        status, data = await self._raw_request(
            "POST",
            self._build_alexa_relative_path("listeners/sync"),
            profile,
            timeout_ms,
        )
        return data if status == 200 and isinstance(data, dict) else None
