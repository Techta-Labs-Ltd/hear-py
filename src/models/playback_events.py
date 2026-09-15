from __future__ import annotations

from src.services.logging_control import ApplicationLog

from src.models.feedback import FeedbackService
from src.models.playback import Playback
from src.models.playback_state import PlaybackQueue
from src.models.user import User
from src.utils.content import ContentUtils


class PlaybackEvents:

    def __init__(self, playback: Playback, user: User) -> None:
        self._playback = playback
        self._user = user

    async def finish(self, handler_input, token: str | None, offset_ms: int) -> None:
        state = self._playback.state.current(handler_input)
        if state and not self._playback.state.accepts_event(handler_input, state):
            return
        if not state or state.get("contentId") != token:
            return
        state = self._complete_state(handler_input, state, offset_ms)
        self._save_completed_source(handler_input, state)
        FeedbackService.record_candidate(handler_input, state, completed=True)
        FeedbackService.activate_best(handler_input)
        await self._playback.emit(handler_input, "finished", state)
        self._warn_if_queue_stalled(handler_input, token)

    def _complete_state(self, handler_input, state: dict, offset_ms: int) -> dict:
        return self._playback.observe(
            handler_input,
            offset_ms=offset_ms,
            event_type="finished",
            status="completed",
            completed=True,
        )

    def _save_completed_source(self, handler_input, state: dict) -> None:
        source = {
            "contentId": state.get("contentId"),
            "organizationId": state.get("organizationId"),
            "organizationName": state.get("organizationName"),
            "creatorId": state.get("creatorId"),
            "creatorName": state.get("creatorName"),
            "completedAt": state.get("updatedAt"),
        }
        selected = ContentUtils.pick_content_source(source)
        if not selected:
            return
        source.update(
            {
                "sourceKind": selected["kind"],
                "sourceId": selected["id"],
                "sourceName": selected["name"],
            }
        )
        self._playback.state.save_completed_source(handler_input, source)

    def _warn_if_queue_stalled(self, handler_input, token: str | None) -> None:
        store = self._user.snapshot(handler_input)
        queue = PlaybackQueue.read(store)
        has_prepared_next = bool(self._playback.state.prepared(store))
        if not queue or has_prepared_next:
            return
        index = int(queue.get("currentIndex") or 0)
        total = len(queue["orderedContentIds"])
        if index < total - 1:
            ApplicationLog.warning(
                "Hear: queue could not advance because Alexa sent PlaybackFinished without an accepted PlaybackNearlyFinished enqueue token=%s index=%s total=%s",
                token,
                index,
                total,
            )
