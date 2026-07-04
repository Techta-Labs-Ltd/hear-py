from __future__ import annotations

from config import settings
from src.services.api import search as api_search
from src.services.persistence import get_store, append_to_queue, set_browse_catalog, get_browse_catalog, queue_remaining
from src.utils.browse_catalog import catalog_search_context, has_more_server_pages, build_catalog_from_search_result
from src.utils.lambda_deadline import compute_search_timeout_ms
from src.utils.normalize_content_item import normalize_content_items
from src.utils.search_filters import build_search_filters
from src.utils.session_queue import clone_queue_item


def append_local_catalog_to_queue(handler_input, store: dict) -> bool:
    """Append catalog items that are not already in the queue."""
    catalog = get_browse_catalog(store)
    if not catalog or not catalog.get("items"):
        return False
    existing_ids = {i.get("id") for i in (store.get("upcomingQueue") or []) if isinstance(i, dict) and i.get("id")}
    fresh = [clone_queue_item(i) for i in catalog["items"] if isinstance(i, dict) and i.get("id") and i["id"] not in existing_ids]
    fresh = [f for f in fresh if f]
    if not fresh:
        return False
    append_to_queue(handler_input, fresh)
    return True


async def maybe_refill_session_queue(handler_input, store: dict):
    """Refill the session queue from the server when it runs low."""
    remaining = queue_remaining(store)
    if remaining > (settings.HEAR_QUEUE_REFILL_THRESHOLD or 2):
        return

    try:
        user_id = handler_input.request_envelope.context.System.user.userId
    except Exception:
        return
    if not user_id:
        return

    audio_timeout_ms = min(compute_search_timeout_ms(handler_input) or 3000, 3000)
    active_store = store or get_store(handler_input)

    if append_local_catalog_to_queue(handler_input, active_store):
        return

    existing_ids = {i.get("id") for i in (active_store.get("upcomingQueue") or []) if isinstance(i, dict) and i.get("id")}
    catalog = get_browse_catalog(active_store)

    if catalog and has_more_server_pages(catalog):
        next_page = (catalog.get("currentPage") or 0) + 1
        ctx = catalog_search_context(catalog)
        try:
            payload = build_search_filters(handler_input, active_store, q=ctx.get("q") or "", page=next_page, limit=catalog.get("limit") or settings.search_page_limit)
            res = await api_search(payload, timeout_ms=audio_timeout_ms)
        except Exception:
            return
        if res.get("results"):
            res["results"] = normalize_content_items(res["results"])
            merged = build_catalog_from_search_result(res, **ctx, page=next_page, limit=catalog.get("limit"), existing_catalog=catalog, append=True)
            set_browse_catalog(handler_input, merged, intent=catalog.get("intent"))
            fresh = [clone_queue_item(i) for i in merged["items"] if isinstance(i, dict) and i.get("id") and i["id"] not in existing_ids]
            fresh = [f for f in fresh if f]
            if fresh:
                append_to_queue(handler_input, fresh)
        return

    try:
        payload = build_search_filters(handler_input, active_store, q="", limit=settings.search_page_limit, page=0)
        res = await api_search(payload, timeout_ms=audio_timeout_ms)
    except Exception:
        return
    raw = normalize_content_items((res or {}).get("results") or [])
    if not raw:
        return
    fresh = [clone_queue_item(i) for i in raw if isinstance(i, dict) and i.get("id") and i["id"] not in existing_ids]
    fresh = [f for f in fresh if f]
    if fresh:
        append_to_queue(handler_input, fresh)
