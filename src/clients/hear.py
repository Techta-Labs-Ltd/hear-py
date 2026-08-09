from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from config import settings
from src.clients.pool import HttpPool
from src.services.store import get_store, update_store
from src.utils.normalize_content_item import normalize_content_items
from src.utils.search_payload import ALLOWED_SEARCH_SORTS, normalize_search_payload
from src.utils.skill_request import get_user_id

logger = logging.getLogger(__name__)

ALLOWED_SORT_VALUES = ALLOWED_SEARCH_SORTS

_SEARCH_FILTER_KEYS = ("alexaUserId", "filter", "isLocal", "isRecommended")
_DATE_KEYS = ("publishedFrom", "publishedTo")
_CLIENT_VERSION = "hear-alexa-python"

_EMPTY_SEARCH_RESULT: dict[str, Any] = {
    "results": [],
    "total_hits": 0,
    "total_pages": 0,
    "page": 0,
    "client_message": None,
    "search_relaxation": None,
    "failed": True,
}


def _hash_text(text: str) -> str:
    if not text:
        return ""
    return f"{len(text):d}:{_simple_hash(text)}"


def _simple_hash(text: str) -> int:
    value = 0
    for char in text:
        value = (value * 31 + ord(char)) & 0x7FFFFFFF
    return value


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
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_ms: int | None = None,
        path_prefix: str | None = None,
        retry_count: int | None = None,
        page_limit: int | None = None,
        pool: HttpPool | None = None,
    ) -> None:
        self._api_key = api_key or settings.api_key
        self._base_url = (base_url or settings.api_base_url).rstrip("/")
        self._timeout_ms = timeout_ms if timeout_ms is not None else settings.api_timeout_ms
        self._path_prefix = (path_prefix if path_prefix is not None else getattr(settings, "HEAR_API_PATH_PREFIX", "") or "").strip("/")
        self._retry_count = retry_count if retry_count is not None else settings.api_retry_count
        self._page_limit = page_limit if page_limit is not None else settings.search_page_limit
        self._pool = pool or HttpPool(
            timeout_ms=max((self._timeout_ms or 30_000), 1),
        )

    # ------------------------------------------------------------------ HTTP --

    async def _raw_request(
        self,
        method: str,
        path: str,
        json_data: dict | None = None,
        timeout_ms: int | None = None,
    ) -> tuple[int, dict | list | None]:
        timeout = httpx.Timeout((timeout_ms or self._timeout_ms or 30_000) / 1000.0) if timeout_ms else None
        try:
            client = self._pool.get(
                base_url=self._base_url,
                headers={"X-Api-Key": self._api_key},
            )
            response = await client.request(
                method,
                self._build_api_path(path),
                json=json_data,
                timeout=timeout,
            )
            if not 200 <= response.status_code < 300:
                logger.warning(
                    "Hear API request failed method=%s path=%s status=%s",
                    method,
                    self._build_api_path(path),
                    response.status_code,
                )
                return response.status_code, None
            return response.status_code, response.json()
        except Exception as exc:
            logger.warning(
                "Hear API request error method=%s path=%s error=%s",
                method,
                self._build_api_path(path),
                type(exc).__name__,
            )
            return 0, None

    # ------------------------------------------------------------ path helpers --

    def _build_api_path(self, relative: str) -> str:
        rel = relative.lstrip("/")
        return f"/{self._path_prefix}/{rel}" if self._path_prefix else f"/{rel}"

    def _build_alexa_relative_path(self, relative: str) -> str:
        if self._path_prefix:
            return f"/{relative.strip('/')}"
        return f"/alexa/{relative.strip('/')}"

    def _build_alexa_search_path(self) -> str:
        return self._build_alexa_relative_path("search")

    @staticmethod
    def _is_retryable(status: int) -> bool:
        return status >= 500

    @staticmethod
    def _normalize_search_response(data: dict) -> dict:
        raw_results = data.get("results") or data.get("items") or []
        results = normalize_content_items(raw_results)
        return {
            "results": results,
            "total_hits": data.get("total") if isinstance(data.get("total"), (int, float)) else len(results),
            "total_pages": data.get("totalPages") if isinstance(data.get("totalPages"), (int, float)) else None,
            "page": data.get("page") if isinstance(data.get("page"), (int, float)) else 0,
            "client_message": data.get("client_message") if data.get("client_message") is not None else None,
            "search_relaxation": data.get("search_relaxation") if data.get("search_relaxation") is not None else None,
            "session_key": data.get("session_key") if isinstance(data.get("session_key"), str) and data.get("session_key") else None,
        }

    # ------------------------------------------------------------ public API --

    async def search(
        self,
        payload: dict | None = None,
        timeout_ms: int | None = None,
    ) -> dict:
        payload = normalize_search_payload(payload)
        query = payload["query"]
        body: dict[str, Any] = {
            "query": query,
            "limit": payload.get("limit", self._page_limit),
            "page": payload.get("page", 0),
        }
        for key in _SEARCH_FILTER_KEYS:
            if payload.get(key) is not None:
                body[key] = payload[key]
        filters = dict(body.get("filter") or {})
        for key in _DATE_KEYS:
            if key not in filters and payload.get(key) is not None:
                filters[key] = payload[key]
        if filters:
            body["filter"] = filters
        if payload.get("sort") in ALLOWED_SORT_VALUES:
            body["sort"] = payload["sort"]

        path = self._build_alexa_search_path()
        query_text = body.get("query") or ""
        logger.info(
            "Hear API search request path=%s queryHash=%s queryChars=%s "
            "filterKeys=%s alexaUserIdPresent=%s",
            path,
            _hash_text(str(query_text)),
            len(str(query_text)),
            sorted((body.get("filter") or {}).keys()),
            bool(body.get("alexaUserId")),
        )
        for attempt in range(self._retry_count + 1):
            status, data = await _request("POST", path, body, timeout_ms)
            logger.info("Hear API search response attempt=%s status=%s", attempt + 1, status)
            if status == 200 and isinstance(data, dict):
                return {**self._normalize_search_response(data), "failed": False}
            if attempt < self._retry_count and self._is_retryable(status):
                await asyncio.sleep(0.2 * (2 ** attempt))
            else:
                break
        return dict(_EMPTY_SEARCH_RESULT)

    async def sync_listener(
        self,
        profile: dict,
        *,
        timeout_ms: int | None = None,
    ) -> dict | None:
        alexa_user_id = profile.get("alexaUserId") if isinstance(profile, dict) else None
        if not alexa_user_id:
            return None
        status, data = await _request(
            "POST",
            self._build_alexa_relative_path("listeners/sync"),
            profile,
            timeout_ms,
        )
        return data if status == 200 and isinstance(data, dict) else None

    # --------------------------------------------------- listener sync helper --

    @staticmethod
    def _request_context(handler_input) -> tuple[str | None, str | None, str | None]:
        request = getattr(handler_input.request_envelope, "request", None)
        locale = getattr(request, "locale", None)
        try:
            system = handler_input.request_envelope.context.System
            device_id = system.device.deviceId
            api_endpoint = system.apiEndpoint
        except (AttributeError, KeyError):
            device_id = None
            api_endpoint = None
        return device_id, api_endpoint, locale

    @staticmethod
    def build_listener_sync_profile(handler_input, store: dict) -> dict | None:
        alexa_user_id = get_user_id(handler_input)
        if not alexa_user_id:
            return None
        device_id, api_endpoint, locale = HearApiClient._request_context(handler_input)
        recent = [
            item.get("contentId")
            for item in (store.get("recentTrackListens") or store.get("history") or [])
            if isinstance(item, dict) and item.get("contentId")
        ]
        return {
            "alexaUserId": alexa_user_id,
            "deviceId": device_id,
            "apiEndpoint": api_endpoint,
            "locale": locale,
            "userName": (
                store.get("userName")
                or store.get("fullName")
                or store.get("givenName")
            ),
            "userEmail": store.get("userEmail"),
            "address": store.get("address"),
            "city": store.get("userCity") or store.get("city"),
            "state": store.get("state"),
            "country": store.get("country"),
            "countryCode": store.get("deviceCountryCode") or store.get("countryCode"),
            "postalCode": store.get("devicePostalCode") or store.get("postalCode"),
            "latitude": store.get("latitude"),
            "longitude": store.get("longitude"),
            "clientVersion": _CLIENT_VERSION,
            "locality": store.get("locality"),
            "listeningPattern": store.get("listeningPattern"),
            "followedCreatorIds": [
                str(item["id"])
                for item in (store.get("followedCreators") or [])
                if isinstance(item, dict)
                and item.get("id")
                and item.get("type", "creator") == "creator"
            ],
            "playbackSpeed": store.get("playbackSpeed"),
            "playCount": int(store.get("playCount") or 0),
            "lastPlayedAt": store.get("lastPlayedAt"),
            "recentPlayedIds": list(dict.fromkeys(recent))[-20:],
            "recentPlays": list(store.get("recentTrackListens") or [])[-20:],
        }

    async def sync_listener_for_launch(self, handler_input) -> bool:
        store = get_store(handler_input)
        profile = build_listener_sync_profile(handler_input, store)
        if not profile:
            return False
        logger.info(
            "Hear: listener sync request fields=%s hasLocation=%s playCount=%s",
            sorted(key for key, value in profile.items() if value not in (None, [], {})),
            bool(profile.get("locality") or profile.get("city")),
            profile.get("playCount", 0),
        )
        result = await sync_listener(profile, timeout_ms=2500)
        if not result:
            logger.warning("Hear: listener sync failed")
            return False
        listener_id = result.get("listenerId") or result.get("id")
        update_store(handler_input, {
            "listenerId": listener_id or store.get("listenerId"),
            "listenerSyncedAt": int(time.time() * 1000),
        })
        logger.info(
            "Hear: listener sync success hasListenerId=%s",
            bool(listener_id or store.get("listenerId")),
        )
        return True


# --- module-level singleton --------------------------------------------------

client = HearApiClient()

search = client.search
sync_listener = client.sync_listener
sync_listener_for_launch = client.sync_listener_for_launch
build_listener_sync_profile = client.build_listener_sync_profile

# module-level aliases for direct test imports
_build_api_path = client._build_api_path
_build_alexa_relative_path = client._build_alexa_relative_path
_build_alexa_search_path = client._build_alexa_search_path
_request = client._raw_request
