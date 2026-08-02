from __future__ import annotations
import asyncio
import json
import logging
import httpx
from config import settings
from src.utils.normalize_content_item import normalize_content_items
from src.utils.search_query import normalize_search_query

logger = logging.getLogger(__name__)

ALLOWED_SORT_VALUES = {"recommended", "nearest", "popular", "latest"}


class HearApiClient:
    async def request(
        self,
        method: str,
        path: str,
        json_data: dict | None = None,
        timeout_ms: int | None = None,
    ) -> tuple[int, dict | list | None]:
        extra = {}
        if timeout_ms is not None:
            extra["timeout"] = httpx.Timeout(timeout_ms / 1000.0)
        try:
            timeout_seconds = (settings.api_timeout_ms or 30000) / 1000.0
            async with httpx.AsyncClient(
                base_url=(settings.api_base_url or "").rstrip("/"),
                timeout=httpx.Timeout(timeout_seconds),
                headers={"X-Api-Key": settings.api_key},
            ) as client:
                response = await client.request(
                    method,
                    _build_api_path(path),
                    json=json_data,
                    **extra,
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


def _excerpt_error_body(data, max_len: int = 240) -> str:
    if data is None:
        return ""
    if isinstance(data, (bytes, str)):
        s = str(data)
        return s[:max_len]
    s = str(data)
    return s[:max_len] + "...[truncated]" if len(s) > max_len else s


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
    for f in (
        "alexaUserId", "filter", "isLocal", "isRecommended",
        "publishedFrom", "publishedTo",
    ):
        if payload.get(f) is not None:
            body[f] = payload[f]
    if payload.get("sort") in ALLOWED_SORT_VALUES:
        body["sort"] = payload["sort"]

    path = _build_alexa_search_path()
    logger.info(
        "Hear API search request path=%s url=%s body=%s",
        path,
        f"{(settings.api_base_url or '').rstrip('/')}{path}",
        json.dumps(body, default=str, ensure_ascii=False)[:2400],
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


async def resolve_locality(payload: dict | None = None) -> dict | None:
    """Resolve a set of coordinates/address into a locality record."""
    payload = payload or {}
    body: dict[str, object] = {
        "postalCode": payload.get("postalCode") or None,
        "countryCode": payload.get("countryCode") or None,
        "latitude": payload.get("latitude") or None,
        "longitude": payload.get("longitude") or None,
    }
    if payload.get("q"):
        body["q"] = payload["q"]
    if payload.get("user") and isinstance(payload["user"], dict):
        body["user"] = payload["user"]
    status, data = await _request("POST", "/listeners/resolve-locality", body)
    if status == 200 and isinstance(data, dict):
        return {
            "locality": data.get("locality") or None,
            "city": data.get("city") or None,
            "state": data.get("state") or None,
            "country": data.get("country") or None,
            "countryCode": data.get("countryCode") or None,
            "address": data.get("address") or None,
            "latitude": data.get("latitude") if isinstance(data.get("latitude"), (int, float)) else None,
            "longitude": data.get("longitude") if isinstance(data.get("longitude"), (int, float)) else None,
        }
    return None


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
