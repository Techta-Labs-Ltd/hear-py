from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.alexa.context import RequestContext
from src.alexa.feedback_service import FeedbackService
from src.alexa.playback_state import PlaybackQueue
from src.alexa.playback_workflow import Playback
from src.models.user import User
from src.services.logging_control import ApplicationLog
from src.utils.content import ContentUtils


@dataclass(frozen=True, slots=True)
class PlaybackEventCommand:
    kind: Literal[
        "started", "nearly_finished", "finished", "stopped", "failed", "progress"
    ]
    token: str
    offset_ms: int = 0

    def __post_init__(self) -> None:
        if self.kind not in {
            "started",
            "nearly_finished",
            "finished",
            "stopped",
            "failed",
            "progress",
        }:
            raise ValueError("unsupported playback event")
        if not isinstance(self.token, str) or not self.token.strip():
            raise ValueError("playback event requires a token")
        if self.offset_ms < 0:
            raise ValueError("playback offset cannot be negative")


@dataclass(frozen=True, slots=True)
class PlaybackEventReceipt:
    command: PlaybackEventCommand
    accepted: bool
    state: dict | None = None
    enqueue_next: bool = False
    notify_started: bool = False
    notify_failed: bool = False


class PlaybackEvents:

    def __init__(self, playback: Playback, user: User) -> None:
        self._playback = playback
        self._user = user

    async def apply(
        self, request: RequestContext, command: PlaybackEventCommand
    ) -> PlaybackEventReceipt:
        handler_input = request.handler_input
        state = self._playback.state.current(handler_input)
        if state and not self._playback.state.accepts_event(handler_input, state):
            return PlaybackEventReceipt(command, accepted=False)

        if command.kind == "started":
            return await self._start(request, command, state)
        if not state or state.get("contentId") != command.token:
            return PlaybackEventReceipt(command, accepted=False)
        if command.kind == "nearly_finished":
            offset_ms = command.offset_ms or int(state.get("offsetMs") or 0)
            observed = self._playback.observe(
                handler_input,
                offset_ms=offset_ms,
                event_type="nearly_finished",
                status="playing",
            )
            await self._playback.emit(handler_input, "nearly_finished", observed)
            return PlaybackEventReceipt(command, accepted=True, state=observed, enqueue_next=True)
        if command.kind == "finished":
            return await self._finish(request, command, state)
        if command.kind == "stopped":
            observed = self._playback.observe(
                handler_input,
                offset_ms=command.offset_ms,
                event_type="stopped",
                status="paused",
            )
            await self._playback.emit(handler_input, "stopped", observed)
            return PlaybackEventReceipt(command, accepted=True, state=observed)
        if command.kind == "failed":
            observed = self._playback.observe(
                handler_input,
                offset_ms=int(state.get("offsetMs") or 0),
                event_type="failed",
                status="failed",
            )
            await self._playback.emit(handler_input, "failed", observed)
            self._playback.state.clear_prepared(handler_input)
            return PlaybackEventReceipt(
                command, accepted=True, state=observed, notify_failed=True
            )
        if state.get("status") not in {"starting", "playing", "paused"}:
            return PlaybackEventReceipt(command, accepted=False)
        observed = self._playback.observe(
            handler_input,
            offset_ms=command.offset_ms,
            event_type="progress",
            status="playing",
        )
        await self._playback.emit(handler_input, "progress", observed)
        return PlaybackEventReceipt(command, accepted=True, state=observed)

    async def _start(
        self,
        request: RequestContext,
        command: PlaybackEventCommand,
        state: dict | None,
    ) -> PlaybackEventReceipt:
        handler_input = request.handler_input
        if state and state.get("contentId") == command.token:
            observed = self._playback.observe(
                handler_input,
                offset_ms=command.offset_ms,
                event_type="started",
                status="playing",
            )
            await self._playback.emit(handler_input, "started", observed)
            return PlaybackEventReceipt(
                command, accepted=True, state=observed, notify_started=True
            )
        prepared = self._playback.state.prepared(self._user.snapshot(handler_input))
        if not isinstance(prepared, dict) or prepared.get("contentId") != command.token:
            return PlaybackEventReceipt(command, accepted=False)
        queue_index = self._playback.queue.set_index_for_content(handler_input, command.token) or 0
        queue = self._playback.queue.read(self._user.snapshot(handler_input))
        self._playback.start_session(
            handler_input,
            prepared,
            queue_id=queue.get("queueId") if queue else None,
            queue_index=queue_index,
            offset_ms=command.offset_ms,
        )
        self._playback.state.clear_prepared(handler_input)
        state = self._playback.state.current(handler_input)
        if not state or state.get("contentId") != command.token:
            return PlaybackEventReceipt(command, accepted=False)
        observed = self._playback.observe(
            handler_input,
            offset_ms=command.offset_ms,
            event_type="started",
            status="playing",
        )
        await self._playback.emit(handler_input, "started", observed)
        return PlaybackEventReceipt(command, accepted=True, state=observed, notify_started=True)

    async def _finish(
        self,
        request: RequestContext,
        command: PlaybackEventCommand,
        state: dict,
    ) -> PlaybackEventReceipt:
        handler_input = request.handler_input
        state = self._complete_state(handler_input, state, command.offset_ms)
        self._save_completed_source(handler_input, state)
        FeedbackService.record_candidate(handler_input, state, completed=True)
        FeedbackService.activate_best(handler_input)
        await self._playback.emit(handler_input, "finished", state)
        self._warn_if_queue_stalled(handler_input, command.token)
        return PlaybackEventReceipt(command, accepted=True, state=state)

    def _complete_state(self, handler_input, state: dict, offset_ms: int) -> dict:
        observed = self._playback.observe(
            handler_input,
            offset_ms=offset_ms,
            event_type="finished",
            status="completed",
            completed=True,
        )
        return observed if isinstance(observed, dict) else state

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
                "Hear: queue could not advance because Alexa sent PlaybackFinished without an accepted PlaybackNearlyFinished enqueue index=%s total=%s",
                index,
                total,
            )
