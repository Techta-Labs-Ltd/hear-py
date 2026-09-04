from __future__ import annotations

import logging
from typing import Any

from ask_sdk_core.handler_input import HandlerInput

from config import settings
from src.alexa.playback import AlexaPlayback, PlayDirective
from src.alexa.playback_speech import PlaybackSpeech
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.clients.alexa import AlexaClient
from src.clients.hear import HearApiClient
from src.models.feedback import FeedbackService
from src.models.playback_history import PlaybackHistory
from src.models.playback_state import PlaybackQueue, PlaybackState
from src.models.user import User
from src.services.alexa_reminder import AlexaReminderService
from src.services.events import OutboundEventService
from src.utils.content import ContentUtils
from src.utils.content_normalizer import ContentNormalizer
from src.utils.deadline import DeadlineBudget
from src.utils.filters import SearchFilters
from src.utils.playback import PlaybackUtils
from src.utils.search_payload import SearchPayload


class Playback:
    async def enqueue_next_queued_content(
        self, handler_input, token: str, hear_client: HearApiClient
    ):
        store = User.snapshot(handler_input)
        state = self.state.current(handler_input)
        if not state or state.get("contentId") != token:
            return handler_input.response_builder.response
        queue = PlaybackQueue.read(store)
        if not queue:
            return handler_input.response_builder.response
        next_index = int(queue.get("currentIndex") or 0) + 1
        if next_index >= len(queue["orderedContentIds"]):
            loaded = await self.queue.load_next_page(handler_input, hear_client)
            if not loaded:
                return handler_input.response_builder.response
            store = User.snapshot(handler_input)
            queue = PlaybackQueue.read(store)
            if not queue:
                return handler_input.response_builder.response
            next_index = int(queue.get("currentIndex") or 0) + 1
            if next_index >= len(queue["orderedContentIds"]):
                return handler_input.response_builder.response
        next_id = queue["orderedContentIds"][next_index]
        prepared = store.get("preparedNextContent")
        if isinstance(prepared, dict) and prepared.get("contentId") == next_id:
            Playback.logger.info(
                "Hear: queue item already prepared current=%s next=%s index=%s",
                token,
                next_id,
                next_index,
            )
            return handler_input.response_builder.response
        content = PlaybackQueue.cached_content(store, next_id)
        if not content:
            payload = SearchPayload.with_identity(
                {
                    "query": "",
                    "filter": SearchFilters.content(next_id),
                    "page": 0,
                    "limit": 1,
                },
                alexa_user_id=AlexaRequest.get_user_id(handler_input),
                listener_id=store.get("listenerId"),
            )
            result = await hear_client.search(
                payload,
                timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
            )
            if not result.get("results"):
                Playback.logger.warning(
                    "Hear: queue prefetch found no content current=%s next=%s index=%s",
                    token,
                    next_id,
                    next_index,
                )
                return handler_input.response_builder.response
            content = result["results"][0]
        content = PlaybackQueue.apply_publication_context(
            User.snapshot(handler_input),
            content,
            queue_index=next_index,
        )
        self.state.prepare_next(handler_input, content)
        playback_speeds = content.get("playbackSpeeds") or []
        audio_url = PlaybackUtils.resolve_audio_url(
            content["audioUrl"],
            store.get("playbackSpeed", settings.default_speed),
            playback_speeds,
        )
        directive = AlexaPlayback.build_play_directive(
            PlayDirective(
                url=audio_url,
                token=content["contentId"],
                previous_token=token,
                metadata=AlexaPlayback.build_content_metadata(content),
                progress_report=True,
                duration_secs=content["durationMs"] / 1000
                if isinstance(content.get("durationMs"), (int, float))
                else None,
            )
        )
        Playback.logger.info(
            "Hear: queue item enqueued current=%s next=%s index=%s",
            token,
            next_id,
            next_index,
        )
        return handler_input.response_builder.add_directive(directive).response

    logger = logging.getLogger(__name__)
    __slots__ = ("_alexa", "_playback", "_queue", "_reminders", "_events")

    def __init__(
        self,
        alexa: AlexaClient,
        playback: PlaybackState | None = None,
        queue: PlaybackQueue | None = None,
        reminders: AlexaReminderService | None = None,
        events: OutboundEventService | None = None,
    ) -> None:
        self._alexa = alexa
        self._playback = playback or PlaybackState(User())
        self._queue = queue or PlaybackQueue(User())
        self._reminders = reminders or AlexaReminderService(alexa, User())
        self._events = events

    @property
    def state(self) -> PlaybackState:
        return self._playback

    @property
    def queue(self) -> PlaybackQueue:
        return self._queue

    async def start(
        self,
        handler_input,
        content: dict,
        intro_text: str,
        track_index: int = 0,
        options: dict | None = None,
    ):
        return await Playback.start_playback(
            handler_input,
            content,
            intro_text,
            track_index,
            options,
            reminders=self._reminders,
            playback_repository=self._playback,
        )

    async def resume(self, handler_input, state: dict, intro_text: str):
        return await Playback.resume_playback(
            handler_input, state, intro_text, playback_repository=self._playback
        )

    def start_session(
        self,
        handler_input,
        content: dict,
        *,
        queue_id: str | None = None,
        queue_index: int = 0,
        offset_ms: int = 0,
    ) -> dict:
        if Playback._finalize_other_publication_feedback(
            handler_input, content.get("publicationId")
        ):
            Playback._activate_best_feedback_candidate(handler_input)
        FeedbackService.dismiss(handler_input)
        state = self._playback.start(
            handler_input,
            content,
            queue_id=queue_id,
            queue_index=queue_index,
            offset_ms=offset_ms,
        )
        PlaybackHistory.add(handler_input, content)
        return state

    async def emit(self, handler_input, event_type: str, state: dict | None = None) -> bool:
        active = dict(state or self._playback.current(handler_input) or {})
        user_id = AlexaRequest.get_user_id(handler_input)
        if (
            self._events is None
            or not user_id
            or not active
            or not active.get("contentId")
            or not active.get("sessionId")
        ):
            return False
        if active.get("publicationId"):
            active.update(
                FeedbackService.publication_listening_metrics(
                    User.snapshot(handler_input),
                    str(active["publicationId"]),
                )
            )
        return self._events.playback(
            alexa_user_id=user_id,
            listener_id=User.snapshot(handler_input).get("listenerId"),
            state=active,
            event_type=event_type,
        )

    def observe(
        self,
        handler_input,
        *,
        offset_ms: int,
        event_type: str,
        status: str,
        completed: bool = False,
    ) -> dict | None:
        state = self._playback.observe(
            handler_input,
            offset_ms=offset_ms,
            event_type=event_type,
            status=status,
            completed=completed,
        )
        if not state:
            return None
        self._playback.save_position(handler_input, state["contentId"], state["offsetMs"])
        PlaybackHistory.update(handler_input, state, completed=completed)
        FeedbackService.update_publication_progress(
            handler_input,
            state,
            completed=completed,
        )
        return state

    async def emit_user(
        self,
        handler_input,
        options: dict | None = None,
        *,
        event_type=None,
        event_label=None,
    ) -> bool:
        options = options or {}
        return await self.emit(
            handler_input,
            event_label
            or event_type
            or options.get("eventLabel")
            or options.get("eventType")
            or "event",
        )

    async def flush_previous(
        self,
        alexa_user_id: str,
        override_offset_ms: int | None = None,
        handler_input=None,
    ) -> dict | None:
        """Persist an unfinished item as paused; never create duplicate state."""
        del alexa_user_id
        if handler_input is None:
            return None
        state = self._playback.current(handler_input)
        if not state or state.get("status") not in {"starting", "playing", "paused"}:
            return None
        patch = {"status": "paused"}
        if override_offset_ms is not None:
            patch["offsetMs"] = max(0, int(override_offset_ms))
        state = self._playback.merge(handler_input, patch)
        await self.emit(handler_input, "paused", state)
        return state

    @staticmethod
    def _activate_best_feedback_candidate(handler_input):
        return FeedbackService.activate_best(handler_input)

    @staticmethod
    def _finalize_other_publication_feedback(handler_input, publication_id):
        return FeedbackService.finalize_other_publications(handler_input, publication_id)

    @staticmethod
    def open_queue_response(handler_input: HandlerInput, speech: str):
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def queue_finished_speech(queue: dict | None) -> str:
        if isinstance(queue, dict) and queue.get("publicationId"):
            return PlaybackSpeech.PUBLICATION_QUEUE_FINISHED
        return PlaybackSpeech.QUEUE_FINISHED

    @staticmethod
    async def _find_queue_content(
        handler_input: HandlerInput, content_id: str, *, deps
    ) -> dict | None:
        payload = SearchPayload.with_identity(
            {
                "query": "",
                "filter": SearchFilters.content(content_id),
                "page": 0,
                "limit": 1,
            },
            alexa_user_id=AlexaRequest.get_user_id(handler_input),
            listener_id=User.snapshot(handler_input).get("listenerId"),
        )
        result = await deps.heara.search(
            payload,
            timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
        )
        return next(
            (item for item in result.get("results", []) if item.get("contentId") == content_id),
            None,
        )

    @staticmethod
    async def play_queue_delta(handler_input: HandlerInput, delta: int, speech: str, *, deps=None):
        if deps is None:
            raise RuntimeError("Playback requires injected dependencies")
        content_id = deps.playback.queue.move(handler_input, delta)
        if not content_id and delta > 0:
            loaded = await deps.playback.queue.load_next_page(handler_input, deps.heara)
            if loaded:
                content_id = deps.playback.queue.move(handler_input, delta)
        if not content_id:
            queue = PlaybackQueue.read(deps.user.snapshot(handler_input))
            if delta > 0 and queue and not PlaybackQueue.has_more_pages(queue):
                message = Playback.queue_finished_speech(queue)
            else:
                message = PlaybackSpeech.NO_PREVIOUS if delta < 0 else Speech.NO_CONTENT_AVAILABLE
            return Playback.open_queue_response(
                handler_input,
                message,
            )
        content = PlaybackQueue.cached_content(deps.user.snapshot(handler_input), content_id)
        if not content:
            content = await Playback._find_queue_content(handler_input, content_id, deps=deps)
        if not content:
            deps.playback.queue.move(handler_input, -delta)
            return Playback.open_queue_response(handler_input, Speech.NO_CONTENT_AVAILABLE)
        store = deps.user.snapshot(handler_input)
        queue = PlaybackQueue.read(store)
        content = PlaybackQueue.apply_publication_context(
            store,
            content,
            queue_index=int(queue.get("currentIndex") or 0) if queue else None,
        )
        return await deps.playback.start(handler_input, content, speech)

    @staticmethod
    def read_playback_session(store: dict) -> dict | None:
        return PlaybackState.from_store(store)

    @staticmethod
    def write_playback_session(handler_input, fields: dict) -> dict | None:
        return PlaybackState(User()).merge(handler_input, fields)

    @staticmethod
    def create_playback_session(
        handler_input,
        content: dict,
        *,
        queue_id: str | None = None,
        queue_index: int = 0,
        offset_ms: int = 0,
    ) -> dict:
        if Playback._finalize_other_publication_feedback(
            handler_input, content.get("publicationId")
        ):
            Playback._activate_best_feedback_candidate(handler_input)
        FeedbackService.dismiss(handler_input)
        return PlaybackState(User()).start(
            handler_input,
            content,
            queue_id=queue_id,
            queue_index=queue_index,
            offset_ms=offset_ms,
        )

    @staticmethod
    def has_unfinished_playback(store: dict) -> bool:
        return PlaybackState(User()).has_unfinished(store)

    @staticmethod
    def _play_response(handler_input: HandlerInput, intro_text: str, directive: dict) -> dict:
        """Hand AudioPlayer control to Alexa and close the foreground session."""
        return (
            handler_input.response_builder.speak(Ssml.ssml(intro_text))
            .add_directive(directive)
            .set_should_end_session(True)
            .response
        )

    @staticmethod
    async def prepare_playback_audio_and_store(
        handler_input: HandlerInput,
        content: dict[str, Any],
        offset_ms: int = 0,
        *,
        playback_repository: PlaybackState | None = None,
    ) -> dict | None:
        """Validate content and create canonical starting playback state."""
        if not ContentNormalizer.is_playable_content_item(content):
            return None
        store = User.snapshot(handler_input)
        speeds = content.get("playbackSpeeds") or []
        effective_speed = PlaybackUtils.resolve_effective_speed(
            store.get("playbackSpeed", settings.default_speed), speeds
        )
        queue = PlaybackQueue.read(store)
        queue_id = queue.get("queueId") if queue else None
        queue_index = queue.get("currentIndex", 0) if queue else 0
        repository = playback_repository or PlaybackState(User())
        if Playback._finalize_other_publication_feedback(
            handler_input, content.get("publicationId")
        ):
            Playback._activate_best_feedback_candidate(handler_input)
        FeedbackService.dismiss(handler_input)
        state = repository.start(
            handler_input,
            content,
            queue_id=queue_id,
            queue_index=queue_index,
            offset_ms=offset_ms,
        )
        title = ContentUtils.content_title_for_speech(content)
        creator = ContentUtils.pick_content_credit(content)
        repository.save_current_content(
            handler_input, content, title=title, creator=creator, offset_ms=offset_ms
        )
        PlaybackHistory.add(handler_input, content)
        audio_url = PlaybackUtils.resolve_audio_url(content["audioUrl"], effective_speed, speeds)
        return {"state": state, "audioUrl": audio_url}

    @staticmethod
    async def start_playback(
        handler_input: HandlerInput,
        content: dict[str, Any],
        intro_text: str,
        track_index: int = 0,
        options: dict[str, Any] | None = None,
        **dependencies,
    ):
        """Return a play response using contentId as the stable Alexa token."""
        del track_index
        reminders: AlexaReminderService = dependencies["reminders"]
        playback_repository: PlaybackState | None = dependencies.get("playback_repository")
        await reminders.cancel(handler_input)
        offset_ms = int((options or {}).get("offsetMs") or 0)
        prepared = await Playback.prepare_playback_audio_and_store(
            handler_input, content, offset_ms, playback_repository=playback_repository
        )
        if not prepared:
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.NO_CONTENT_AVAILABLE))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        state = prepared["state"]
        directive = AlexaPlayback.build_play_directive(
            PlayDirective(
                url=prepared["audioUrl"],
                token=state["contentId"],
                offset_ms=state["offsetMs"],
                metadata=AlexaPlayback.build_content_metadata(content),
                progress_report=True,
                duration_secs=state["durationMs"] / 1000
                if isinstance(state.get("durationMs"), (int, float))
                else None,
            )
        )
        if not directive:
            Playback.logger.error(
                "Hear: could not build play directive contentId=%s", state["contentId"]
            )
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.NO_CONTENT_AVAILABLE))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        repository = playback_repository or PlaybackState(User())
        repository.save_audio_url(handler_input, prepared["audioUrl"])
        return Playback._play_response(handler_input, intro_text, directive)

    @staticmethod
    async def resume_playback(
        handler_input: HandlerInput,
        state: dict[str, Any],
        intro_text: str,
        *,
        playback_repository: PlaybackState | None = None,
    ):
        """Resume directly from canonical persisted playback state.

        Resume must not depend on a catalog lookup: the backend may no longer
        return the item, and the active record already owns the stable token,
        playable URL, metadata, and exact offset.
        """
        content_id = str(state.get("contentId") or "").strip()
        audio_url = str(
            state.get("audioUrl") or User.snapshot(handler_input).get("currentAudioUrl") or ""
        ).strip()
        content = {
            "contentId": content_id,
            "title": state.get("title"),
            "spokenTitle": state.get("title"),
            "audioUrl": audio_url,
            "creatorId": state.get("creatorId"),
            "creatorName": state.get("creatorName"),
            "publicationId": state.get("publicationId"),
            "publicationTitle": state.get("publicationTitle"),
            "durationMs": state.get("durationMs"),
            "playbackSpeeds": state.get("playbackSpeeds")
            or User.snapshot(handler_input).get("currentPlaybackSpeeds")
            or [],
        }
        if not ContentNormalizer.is_playable_content_item(content):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.NO_CONTENT_AVAILABLE))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        offset_ms = max(0, int(state.get("offsetMs") or 0))
        speeds = content["playbackSpeeds"]
        effective_speed = PlaybackUtils.resolve_effective_speed(
            User.snapshot(handler_input).get("playbackSpeed", settings.default_speed),
            speeds,
        )
        resolved_url = PlaybackUtils.resolve_audio_url(audio_url, effective_speed, speeds)
        repository = playback_repository or PlaybackState(User())
        resumed = repository.merge(handler_input, {"status": "starting", "offsetMs": offset_ms})
        repository.save_resumed_content(
            handler_input,
            content_id=content_id,
            title=state.get("title"),
            audio_url=audio_url,
            offset_ms=offset_ms,
        )
        directive = AlexaPlayback.build_play_directive(
            PlayDirective(
                url=resolved_url,
                token=content_id,
                offset_ms=offset_ms,
                metadata=AlexaPlayback.build_content_metadata(content),
                progress_report=True,
                duration_secs=resumed["durationMs"] / 1000
                if resumed and isinstance(resumed.get("durationMs"), (int, float))
                else None,
            )
        )
        if not directive:
            repository.merge(handler_input, {"status": "failed"})
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.NO_CONTENT_AVAILABLE))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        repository.save_audio_url(handler_input, resolved_url)
        return Playback._play_response(handler_input, intro_text, directive)

    @staticmethod
    async def _resolve_content(
        handler_input, content_id: str, *, hear_client: HearApiClient
    ) -> dict | None:
        store = User.snapshot(handler_input)
        cached = PlaybackQueue.cached_content(store, content_id)
        if cached:
            return PlaybackQueue.apply_publication_context(store, cached)
        payload = SearchPayload.with_identity(
            {
                "query": "",
                "filter": SearchFilters.content(content_id),
                "page": 0,
                "limit": 1,
            },
            alexa_user_id=AlexaRequest.get_user_id(handler_input),
            listener_id=store.get("listenerId"),
        )
        result = await hear_client.search(
            payload,
            timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
        )
        content = result["results"][0] if result.get("results") else None
        return (
            PlaybackQueue.apply_publication_context(
                User.snapshot(handler_input),
                content,
            )
            if content
            else None
        )

    @staticmethod
    async def play_next_queued_item(
        handler_input,
        *,
        hear_client: HearApiClient,
        reminders: AlexaReminderService,
        speak_intro: bool = True,
        intro_prefix: str | None = None,
    ):
        """Advance the canonical queue and resolve its next content through search."""
        content_id = PlaybackQueue(User()).move(handler_input, 1)
        if not content_id:
            return None
        content = await Playback._resolve_content(
            handler_input, content_id, hear_client=hear_client
        )
        if not content:
            return None
        title = ContentUtils.content_title_for_speech(content)
        credit = ContentUtils.pick_content_credit(content)
        intro = Speech.LOCAL_CONTENT_FALLBACK(title, credit) if speak_intro else ""
        if intro_prefix:
            intro = f"{intro_prefix} {intro}".strip()
        return await Playback.start_playback(handler_input, content, intro, reminders=reminders)
