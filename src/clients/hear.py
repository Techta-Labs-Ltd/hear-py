from __future__ import annotations
import asyncio
import logging
import threading
import httpx
from config import settings
from src.utils.normalize_content_item import normalize_content_items
from src.utils.search_query import normalize_search_query
import time
from src.services.store import get_store, update_store
from src.utils.skill_request import get_user_id
logger = logging.getLogger(__name__)


ALLOWED_SORT_VALUES = {"recommended", "nearest", "popular", "latest", "trending"}


def _hash_text(text: str) -> str:
    if not text:
        return ""
    return f"{len(text):d}:{_simple_hash(text)}"


def _simple_hash(text: str) -> int:
    value = 0
    for char in text:
        value = (value * 31 + ord(char)) & 0x7FFFFFFF
    return value


_client_pool: dict[int, httpx.AsyncClient] = {}


_client_pool_lock = threading.Lock()


def _pooled_client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    key = id(loop)
    client = _client_pool.get(key)
    if client is None:
        with _client_pool_lock:
            client = _client_pool.get(key)
            if client is None:
                client = httpx.AsyncClient(
                    base_url=(settings.api_base_url or "").rstrip("/"),
                    timeout=httpx.Timeout((settings.api_timeout_ms or 30000) / 1000.0),
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                    headers={"X-Api-Key": settings.api_key},
                )
                _client_pool[key] = client
    return client


class HearApiClient:
    async def request(
        self,
        method: str,
        path: str,
        json_data: dict | None = None,
        timeout_ms: int | None = None,
    ) -> tuple[int, dict | list | None]:
        timeout = None
        if timeout_ms is not None:
            timeout = httpx.Timeout(timeout_ms / 1000.0)
        try:
            response = await _pooled_client().request(
                method,
                _build_api_path(path),
                json=json_data,
                timeout=timeout,
            )
            if not 200 <= response.status_code < 300:
                logger.warning(
                    "Hear API request failed method=%s path=%s status=%s",
                    method,
                    _build_api_path(path),
                    response.status_code,
                )
                return response.status_code, None
            return response.status_code, response.json()
        except Exception as exc:
            logger.warning(
                "Hear API request error method=%s path=%s error=%s",
                method,
                _build_api_path(path),
                type(exc).__name__,
            )
            return 0, None


hear_api_client = HearApiClient()


def _build_api_path(relative: str) -> str:
    prefix = getattr(settings, "HEAR_API_PATH_PREFIX", "") or ""
    prefix = str(prefix).strip("/")
    rel = relative.lstrip("/")
    return f"/{prefix}/{rel}" if prefix else f"/{rel}"


def _build_alexa_relative_path(relative: str) -> str:
    relative = relative.strip("/")
    if getattr(settings, "HEAR_API_PATH_PREFIX", "") and str(settings.HEAR_API_PATH_PREFIX).strip():
        return f"/{relative}"
    return f"/alexa/{relative}"


def _build_alexa_search_path() -> str:
    return _build_alexa_relative_path("search")


def _is_retryable(status: int) -> bool:
    return status >= 500


async def _request(
    method: str,
    path: str,
    json_data: dict | None = None,
    timeout_ms: int | None = None,
) -> tuple[int, dict | list | None]:
    return await hear_api_client.request(method, path, json_data, timeout_ms)


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


async def search(payload: dict | None = None, timeout_ms: int | None = None) -> dict:
    """Search the Hear content catalog.

    Args:
        payload: Search body with keys intent, q, limit, page, user, etc.
        timeout_ms: Per-request timeout override.

    Returns:
        Normalized search response dict; includes ``failed: True`` on error.
    """
    payload = payload or {}
    retries = settings.api_retry_count
    query = payload.get("query")
    if query is None:
        query = payload.get("q")
    body: dict = {
        "query": normalize_search_query(query),
        "limit": payload.get("limit", settings.search_page_limit),
        "page": payload.get("page", 0),
    }
    for f in ("alexaUserId", "filter", "isLocal", "isRecommended"):
        if payload.get(f) is not None:
            body[f] = payload[f]
    # Normalize persisted payloads created before dates moved under filter.
    filters = dict(body.get("filter") or {})
    for key in ("publishedFrom", "publishedTo"):
        if key not in filters and payload.get(key) is not None:
            filters[key] = payload[key]
    if filters:
        body["filter"] = filters
    if payload.get("sort") in ALLOWED_SORT_VALUES:
        body["sort"] = payload["sort"]

    path = _build_alexa_search_path()
    query_text = body.get("query") or ""
    logger.info(
        "Hear API search request path=%s queryHash=%s queryChars=%s filterKeys=%s",
        path,
        _hash_text(str(query_text)),
        len(str(query_text)),
        sorted((body.get("filter") or {}).keys()),
    )

    for attempt in range(retries + 1):
        status, data = await _request("POST", path, body, timeout_ms)
        logger.info("Hear API search response attempt=%s status=%s", attempt + 1, status)
        if status == 200 and isinstance(data, dict):
            return {**_normalize_search_response(data), "failed": False}
        if attempt < retries and _is_retryable(status):
            await asyncio.sleep(0.2 * (2 ** attempt))
        else:
            break
    return {
        "results": [],
        "total_hits": 0,
        "total_pages": 0,
        "page": 0,
        "client_message": None,
        "search_relaxation": None,
        "failed": True,
    }


async def sync_listener(
    profile: dict,
    *,
    timeout_ms: int | None = None,
) -> dict | None:
    """Register or update a listener through the documented sync endpoint."""
    alexa_user_id = profile.get("alexaUserId") if isinstance(profile, dict) else None
    if not alexa_user_id:
        return None
    status, data = await _request(
        "POST",
        _build_alexa_relative_path("listeners/sync"),
        profile,
        timeout_ms,
    )
    return data if status == 200 and isinstance(data, dict) else None

logger = logging.getLogger(__name__)


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


def build_listener_sync_profile(handler_input, store: dict) -> dict | None:
    """Build the documented listener-sync payload from canonical state."""
    alexa_user_id = get_user_id(handler_input)
    if not alexa_user_id:
        return None
    device_id, api_endpoint, locale = _request_context(handler_input)
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
        "clientVersion": "hear-alexa-python",
        "locality": store.get("locality"),
        "listeningPattern": store.get("listeningPattern"),
        "followedCreatorIds": list(store.get("followedCreators") or []),
        "playbackSpeed": store.get("playbackSpeed"),
        "playCount": int(store.get("playCount") or 0),
        "lastPlayedAt": store.get("lastPlayedAt"),
        "recentPlayedIds": list(dict.fromkeys(recent))[-20:],
        "recentPlays": list(store.get("recentTrackListens") or [])[-20:],
    }


async def sync_listener_for_launch(handler_input) -> bool:
    """Upsert the Alexa listener on every foreground launch."""
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
