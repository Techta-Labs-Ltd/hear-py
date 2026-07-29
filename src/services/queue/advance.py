from __future__ import annotations

from src.services.api import search
from src.services.playback.start import start_playback
from src.services.queue.state import cached_queue_content, move_queue
from src.services.storage.persistence import get_store
from src.utils.normalize_content_item import content_title_for_speech, pick_content_credit
from src.utils.skill_request import get_user_id
from src.utils.speech import LOCAL_CONTENT_FALLBACK


async def _resolve_content(handler_input, content_id: str) -> dict | None:
    cached = cached_queue_content(get_store(handler_input), content_id)
    if cached:
        return cached
    result = await search({
        "query": "",
        "filter": {"contentIds": [content_id]},
        "page": 0,
        "limit": 1,
        "alexaUserId": get_user_id(handler_input),
    })
    return result["results"][0] if result.get("results") else None


async def play_next_queued_item(
    handler_input,
    *,
    speak_intro: bool = True,
    intro_prefix: str | None = None,
):
    """Advance the canonical queue and resolve its next content through search."""
    content_id = move_queue(handler_input, 1)
    if not content_id:
        return None
    content = await _resolve_content(handler_input, content_id)
    if not content:
        return None
    title = content_title_for_speech(content)
    credit = pick_content_credit(content)
    intro = LOCAL_CONTENT_FALLBACK(title, credit) if speak_intro else ""
    if intro_prefix:
        intro = f"{intro_prefix} {intro}".strip()
    return await start_playback(handler_input, content, intro)
