from __future__ import annotations

from ask_sdk_core.handler_input import HandlerInput

from config import settings
from src.alexa.playback import AlexaPlayback
from src.alexa.playback_context import PlaybackContext
from src.alexa.playback_speech import PlaybackSpeech
from src.alexa.playback_state import PlaybackQueue
from src.alexa.playback_workflow import Playback
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.models.playback_control_policy import PlaybackControlPolicy
from src.models.search_contracts import CatalogueSearchGateway
from src.models.user import User
from src.utils.deadline import DeadlineBudget
from src.utils.filters import SearchFilters
from src.utils.playback import PlaybackUtils
from src.utils.search_payload import SearchPayload


class PlaybackControls:
    def __init__(
        self,
        playback: Playback,
        user: User,
        heara: CatalogueSearchGateway,
    ) -> None:
        self._playback = playback
        self._user = user
        self._heara = heara

    async def pause_active(self, handler_input: HandlerInput) -> dict:
        state = self._playback.state.current(handler_input)
        audio = PlaybackContext.read_audio_player_context(handler_input)
        audio_state: dict = audio if isinstance(audio, dict) else {}
        active_token = str((state or {}).get("token") or (state or {}).get("contentId") or "")
        audio_token = str(audio_state.get("token") or "")
        if (
            state
            and PlaybackContext.is_audio_player_active(audio)
            and audio_token
            and audio_token == active_token
        ):
            state = self._playback.observe(
                handler_input,
                offset_ms=PlaybackUtils.integer(audio_state.get("offsetMs")),
                event_type="paused",
                status="paused",
            )
        elif state:
            state = self._playback.state.merge(handler_input, {"status": "paused"})
        await self._playback.emit(handler_input, "paused", state)
        return AlexaPlayback.build_stop_directive()

    async def restart_active(
        self,
        handler_input: HandlerInput,
        *,
        offset_ms: int | None = None,
        speech: str = PlaybackSpeech.RESUMING,
    ):
        state = self._playback.state.current(handler_input)
        if not state:
            return Playback.open_queue_response(handler_input, PlaybackSpeech.NOTHING_TO_RESUME)
        resume_state = {
            **state,
            "offsetMs": state.get("offsetMs", 0) if offset_ms is None else offset_ms,
        }
        await self._playback.emit(handler_input, "resumed", resume_state)
        return await self._playback.resume(handler_input, resume_state, speech)

    async def apply_speed(self, handler_input: HandlerInput, speed: float):
        store = self._user.snapshot(handler_input)
        state = self._playback.state.current(handler_input)
        decision = PlaybackControlPolicy.apply_speed(
            state, store, speed, default_speed=settings.default_speed
        )
        if decision.kind == "unavailable":
            available = ", ".join(f"{value}x" for value in decision.available_speeds)
            return Playback.open_queue_response(
                handler_input, PlaybackSpeech.speed_unavailable(speed, available)
            )
        self._playback.state.set_speed(handler_input, speed)
        if decision.kind == "idle":
            return Playback.open_queue_response(
                handler_input, PlaybackSpeech.speed_set(speed, idle=True)
            )
        return await self.restart_active(
            handler_input,
            offset_ms=decision.offset_ms,
            speech=PlaybackSpeech.speed_set(speed),
        )

    async def step_speed(self, handler_input: HandlerInput, direction: str):
        store = self._user.snapshot(handler_input)
        state = self._playback.state.current(handler_input)
        decision = PlaybackControlPolicy.step_speed(
            state, store, direction, default_speed=settings.default_speed
        )
        if decision.kind == "unsupported":
            return Playback.open_queue_response(handler_input, PlaybackSpeech.SPEED_NOT_SUPPORTED)
        if decision.kind == "limit":
            return Playback.open_queue_response(
                handler_input,
                PlaybackSpeech.SPEED_MAX if direction == "up" else PlaybackSpeech.SPEED_MIN,
            )
        if decision.speed is None:
            return Playback.open_queue_response(handler_input, PlaybackSpeech.SPEED_NOT_SUPPORTED)
        return await self.apply_speed(handler_input, decision.speed)

    async def seek(self, handler_input: HandlerInput, direction: int):
        state = self._playback.state.current(handler_input)
        decision = PlaybackControlPolicy.seek(
            state,
            direction,
            AlexaPlayback.resolve_seek_ms(handler_input),
        )
        if decision.kind == "cannot_seek":
            return Playback.open_queue_response(handler_input, PlaybackSpeech.CANNOT_SEEK)
        offset_ms = decision.offset_ms if decision.offset_ms is not None else 0
        speech = PlaybackSpeech.seek(
            direction,
            decision.moved_ms,
            offset_ms,
            decision.duration_ms,
        )
        return await self.restart_active(handler_input, offset_ms=offset_ms, speech=speech)

    async def play_queue_delta(
        self, handler_input: HandlerInput, delta: int, speech: str
    ):
        content_id = self._playback.queue.move(handler_input, delta)
        if not content_id and delta > 0:
            loaded = await self._playback.queue.load_next_page(handler_input, self._heara)
            if loaded:
                content_id = self._playback.queue.move(handler_input, delta)
        if not content_id:
            queue = PlaybackQueue.read(self._user.snapshot(handler_input))
            if delta > 0 and queue and not PlaybackQueue.has_more_pages(queue):
                message = Playback.queue_finished_speech(queue)
            else:
                message = PlaybackSpeech.NO_PREVIOUS if delta < 0 else Speech.NO_CONTENT_AVAILABLE
            return Playback.open_queue_response(handler_input, message)
        content = PlaybackQueue.cached_content(
            self._user.snapshot(handler_input), content_id
        )
        if not content:
            payload = SearchPayload.with_identity(
                {
                    "query": "",
                    "filter": SearchFilters.content(content_id),
                    "page": 0,
                    "limit": 1,
                },
                alexa_user_id=AlexaRequest.get_user_id(handler_input),
                listener_id=self._user.snapshot(handler_input).get("listenerId"),
            )
            result = await self._heara.search(
                payload,
                timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
            )
            content = next(
                (
                    item
                    for item in result.get("results", [])
                    if item.get("contentId") == content_id
                ),
                None,
            )
        if not content:
            self._playback.queue.move(handler_input, -delta)
            return Playback.open_queue_response(handler_input, Speech.NO_CONTENT_AVAILABLE)
        store = self._user.snapshot(handler_input)
        queue = PlaybackQueue.read(store)
        content = PlaybackQueue.apply_publication_context(
            store,
            content,
            queue_index=int(queue.get("currentIndex") or 0) if queue else None,
        )
        return await self._playback.start(handler_input, content, speech)
