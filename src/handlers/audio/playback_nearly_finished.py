from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.services.api import search
from src.services.playback.events import emit_listening_event
from src.services.playback.session import read_playback_session
from src.services.queue.state import read_playback_queue
from src.services.storage.persistence import get_store, update_store
from src.utils.audio import build_content_metadata, build_play_directive
from src.utils.skill_request import get_request_type, get_user_id


class PlaybackNearlyFinishedHandler(AbstractRequestHandler):
    def can_handle(self, handler_input) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackNearlyFinished"

    async def handle(self, handler_input):
        request = handler_input.request_envelope.request
        token = request.token
        store = get_store(handler_input)
        state = read_playback_session(store)
        if not state or state.get("contentId") != token:
            return handler_input.response_builder.response
        queue = read_playback_queue(store)
        if not queue:
            return handler_input.response_builder.response
        next_index = int(queue.get("currentIndex") or 0) + 1
        if next_index >= len(queue["orderedContentIds"]):
            return handler_input.response_builder.response
        next_id = queue["orderedContentIds"][next_index]
        result = await search({
            "query": "",
            "filter": {"contentIds": [next_id]},
            "page": 0,
            "limit": 1,
            "alexaUserId": get_user_id(handler_input),
        })
        if not result.get("results"):
            return handler_input.response_builder.response
        content = result["results"][0]
        update_store(handler_input, {"preparedNextContent": content})
        await emit_listening_event(handler_input, "nearly_finished", state)
        directive = build_play_directive(
            url=content["audioUrl"],
            token=content["contentId"],
            prev_token=token,
            metadata=build_content_metadata(content),
            duration_secs=(
                content["durationMs"] / 1000
                if isinstance(content.get("durationMs"), (int, float))
                else None
            ),
        )
        return handler_input.response_builder.add_directive(directive).response
