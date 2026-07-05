from __future__ import annotations
import asyncio
import time
import uuid
import httpx
from config import settings
from src.utils.normalize_content_item import normalize_content_items

_CLIENT: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return a cached httpx.AsyncClient configured with the Hear API base URL and key."""
    global _CLIENT
    if _CLIENT is None:
        base = (settings.api_base_url or "").rstrip("/")
        timeout_secs = (settings.api_timeout_ms or 30000) / 1000.0
        _CLIENT = httpx.AsyncClient(
            base_url=base,
            timeout=httpx.Timeout(timeout_secs),
            headers={"X-Api-Key": settings.api_key},
        )
    return _CLIENT


def _build_api_path(relative: str) -> str:
    prefix = getattr(settings, "HEAR_API_PATH_PREFIX", "") or ""
    prefix = str(prefix).strip("/")
    rel = relative.lstrip("/")
    return f"/{prefix}/{rel}" if prefix else f"/{rel}"


def _build_alexa_search_path() -> str:
    if getattr(settings, "HEAR_API_PATH_PREFIX", "") and str(settings.HEAR_API_PATH_PREFIX).strip():
        return _build_api_path("/search")
    return _build_api_path("/alexa/search")


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
    client = _get_client()
    url = _build_api_path(path)
    extra: dict = {}
    if timeout_ms is not None:
        extra["timeout"] = httpx.Timeout(timeout_ms / 1000.0)
    try:
        resp = await client.request(method, url, json=json_data, **extra)
        if resp.status_code < 200 or resp.status_code >= 300:
            return resp.status_code, None
        return resp.status_code, resp.json()
    except Exception:
        return 0, None


def _normalize_search_response(data: dict) -> dict:
    raw_results = data.get("results") or data.get("items") or []
    # normalize_content_items drops publications with no tracks (and any item
    # with no playable audio), so unplayable results never reach the skill.
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
    body: dict = {
        "q": str(payload.get("q", "")),
        "limit": payload.get("limit", settings.search_page_limit),
        "page": payload.get("page", 0),
    }
    for f in ("alexaUserId", "sort", "filter"):
        if payload.get(f) is not None:
            body[f] = payload[f]

    path = _build_alexa_search_path()

    for attempt in range(retries + 1):
        status, data = await _request("POST", path, body, timeout_ms)
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


async def save_feedback(
    alexa_user_id: str,
    content_id: str,
    feedback_value: int | str,
    *,
    track_id: str | None = None,
    listened_ms: int | None = None,
    completion_pct: float | None = None,
    played_at: any = None,
    user: dict | None = None,
) -> None:
    """Persist user feedback for a track via the Hear API."""
    if not track_id:
        return
    body: dict[str, object] = {
        "alexaUserId": alexa_user_id,
        "contentId": content_id,
        "trackId": track_id,
        "feedback": feedback_value,
    }
    if listened_ms is not None:
        body["listenedMs"] = listened_ms
    if completion_pct is not None:
        body["completionPct"] = completion_pct
    if played_at is not None:
        body["playedAt"] = played_at
    if user and isinstance(user, dict):
        body["user"] = user
    await _request("POST", "/feedback", body)


async def record_playback_events(
    alexa_user_id: str,
    events: list,
    *,
    refresh_track_ids: list | None = None,
    user: dict | None = None,
) -> dict | None:
    """Send one or more playback events to the Hear backend.

    Returns the API response body on success, or None.
    """
    if not alexa_user_id or not isinstance(events, list) or not events:
        return None
    body: dict[str, object] = {"events": events}
    if refresh_track_ids and isinstance(refresh_track_ids, list) and refresh_track_ids:
        body["refreshTrackIds"] = refresh_track_ids
    if user and isinstance(user, dict):
        body["user"] = user
    path = f"/listeners/{alexa_user_id}/playback/events"
    status, data = await _request("POST", path, body)
    return data if isinstance(data, dict) and status == 200 else None


async def record_playback_started(payload: dict) -> dict | None:
    """Record a playback-started event with a single-event wrapper."""
    alexa_user_id = payload.get("alexaUserId")
    track_id = payload.get("trackId")
    if not alexa_user_id or not track_id:
        return None
    timestamp_ms = round(payload.get("startedAt") or time.time() * 1000)
    session_id = f"{track_id}-{timestamp_ms}"
    event = {
        "trackId": str(track_id),
        "sessionId": session_id,
        "eventType": "AUDIO_PLAYER_PLAYBACK_STARTED",
        "positionMs": 0,
        "trackDurationMs": round((payload.get("durationSecs") or 0) * 1000),
        "timestampMs": timestamp_ms,
        "clientEventId": str(uuid.uuid4()),
    }
    return await record_playback_events(alexa_user_id, [event])


async def record_playback_finished(payload: dict) -> dict | None:
    """Record a playback-finished event with a single-event wrapper."""
    alexa_user_id = payload.get("alexaUserId")
    track_id = payload.get("trackId")
    if not alexa_user_id or not track_id:
        return None
    timestamp_ms = round(payload.get("finishedAt") or time.time() * 1000)
    event = {
        "trackId": str(track_id),
        "sessionId": payload.get("sessionId") or str(track_id),
        "eventType": "AUDIO_PLAYER_PLAYBACK_FINISHED",
        "positionMs": max(0, round(payload.get("listenedMs") or 0)),
        "trackDurationMs": round((payload.get("durationSecs") or 0) * 1000),
        "timestampMs": timestamp_ms,
        "clientEventId": str(uuid.uuid4()),
    }
    return await record_playback_events(alexa_user_id, [event])


async def save_listening_pattern(
    alexa_user_id: str,
    listening_pattern: dict,
    user: dict | None = None,
) -> None:
    """Persist the user's listening pattern to the backend."""
    body: dict[str, object] = {"listeningPattern": listening_pattern}
    if user and isinstance(user, dict):
        body["user"] = user
    await _request("POST", f"/listeners/{alexa_user_id}/pattern", body)


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
            "address": data.get("address") or None,
        }
    return None


async def save_location(alexa_user_id: str, city: str) -> dict | None:
    """Save a user's city and return resolved geo metadata."""
    status, data = await _request("POST", "/alexa/location", {"alexaUserId": alexa_user_id, "city": city})
    if status == 200 and isinstance(data, dict):
        return {
            "locality": data.get("locality") or None,
            "city": data.get("city") or city,
            "state": data.get("state") or None,
            "country": data.get("country") or None,
            "countryCode": data.get("countryCode") or None,
            "postalCode": data.get("postalCode") or None,
            "latitude": data.get("latitude") if isinstance(data.get("latitude"), (int, float)) else None,
            "longitude": data.get("longitude") if isinstance(data.get("longitude"), (int, float)) else None,
        }
    return None


async def report_content(alexa_user_id: str, payload: dict) -> None:
    """Report content for moderation review."""
    if not alexa_user_id or not payload.get("trackId") or not payload.get("contentId"):
        raise ValueError("report_content requires alexaUserId, trackId, and contentId")
    body: dict[str, object] = {
        "alexaUserId": alexa_user_id,
        "trackId": str(payload["trackId"]),
        "contentId": str(payload["contentId"]),
        "reason": payload.get("reason") or "reported_via_alexa",
    }
    if payload.get("title"):
        body["title"] = str(payload["title"])
    if payload.get("creatorId"):
        body["creatorId"] = str(payload["creatorId"])
    if payload.get("locale"):
        body["locale"] = str(payload["locale"])
    if payload.get("deviceId"):
        body["deviceId"] = str(payload["deviceId"])
    if payload.get("user") and isinstance(payload["user"], dict):
        body["user"] = payload["user"]
    await _request("POST", f"/content/tracks/{str(payload['trackId'])}/report", body)


async def report_creator(alexa_user_id: str, creator_id: str, reason: str, user: dict | None = None) -> None:
    """Report a creator for moderation review."""
    body: dict[str, object] = {"alexaUserId": alexa_user_id, "reason": reason}
    if user and isinstance(user, dict):
        body["user"] = user
    await _request("POST", f"/creators/{creator_id}/report", body)


async def follow_creator(alexa_user_id: str, creator_id: str, user: dict | None = None) -> None:
    """Follow a creator so the user receives updates."""
    body: dict[str, object] = {"creatorId": creator_id}
    if user and isinstance(user, dict):
        body["user"] = user
    await _request("POST", f"/listeners/{alexa_user_id}/follow", body)


async def unfollow_creator(alexa_user_id: str, creator_id: str) -> None:
    """Stop following a creator."""
    await _request("DELETE", f"/listeners/{alexa_user_id}/follow/{creator_id}")


async def get_followed_creators(alexa_user_id: str) -> list:
    """Return the list of creators that the user is following."""
    status, data = await _request("GET", f"/listeners/{alexa_user_id}/following")
    if status == 200 and isinstance(data, dict):
        return data.get("creators") or []
    return []


async def register_notification_subscription(payload: dict, timeout_ms: int | None = None) -> None:
    """Subscribe the user to push notifications on the Hear backend."""
    body: dict[str, object] = {
        "alexaUserId": payload.get("alexaUserId"),
        "deviceId": payload.get("deviceId"),
        "categories": payload.get("categories") if isinstance(payload.get("categories"), list) else [],
        "locality": payload.get("locality") or None,
        "listeningPattern": payload.get("listeningPattern") if isinstance(payload.get("listeningPattern"), dict) else {},
        "recentPlayedIds": payload.get("recentPlayedIds") if isinstance(payload.get("recentPlayedIds"), list) else [],
    }
    if payload.get("apiEndpoint"):
        body["apiEndpoint"] = payload["apiEndpoint"]
    if payload.get("locale"):
        body["locale"] = payload["locale"]
    if payload.get("creatorIds") and isinstance(payload["creatorIds"], list) and payload["creatorIds"]:
        body["creatorIds"] = payload["creatorIds"]
    if payload.get("creatorNames") and isinstance(payload["creatorNames"], dict):
        body["creatorNames"] = payload["creatorNames"]
    if payload.get("user") and isinstance(payload["user"], dict):
        body["user"] = payload["user"]
    await _request("POST", "/notifications/subscribe", body, timeout_ms=timeout_ms)


async def update_notification_subscription(payload: dict, timeout_ms: int | None = None) -> None:
    """Update the user's notification subscription on the Hear backend."""
    body: dict[str, object] = {
        "deviceId": payload.get("deviceId"),
        "categories": payload.get("categories") if isinstance(payload.get("categories"), list) else [],
        "listeningPattern": payload.get("listeningPattern") if isinstance(payload.get("listeningPattern"), dict) else {},
        "recentPlayedIds": payload.get("recentPlayedIds") if isinstance(payload.get("recentPlayedIds"), list) else [],
    }
    if payload.get("apiEndpoint"):
        body["apiEndpoint"] = payload["apiEndpoint"]
    if payload.get("locale"):
        body["locale"] = payload["locale"]
    if payload.get("creatorIds") and isinstance(payload["creatorIds"], list) and payload["creatorIds"]:
        body["creatorIds"] = payload["creatorIds"]
    if payload.get("creatorNames") and isinstance(payload["creatorNames"], dict):
        body["creatorNames"] = payload["creatorNames"]
    if payload.get("user") and isinstance(payload["user"], dict):
        body["user"] = payload["user"]
    await _request("PATCH", f"/notifications/subscribe/{payload.get('alexaUserId')}", body, timeout_ms=timeout_ms)


async def unsubscribe_notifications(alexa_user_id: str) -> None:
    """Remove the user's notification subscription."""
    await _request("DELETE", f"/notifications/subscribe/{alexa_user_id}")
