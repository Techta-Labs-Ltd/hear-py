from __future__ import annotations

from typing import Literal

from src.alexa.context import RequestContext
from src.alexa.playback_context import PlaybackContext
from src.alexa.playback_details import PlaybackDetails
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.social import FollowCommand, FollowingManager, Social
from src.services.logging_control import ApplicationLog


class CreatorIdentity:
    """Alexa presentation adapter for creator identity."""

    def __init__(self, details: PlaybackDetails) -> None:
        self._details = details

    async def execute(self, request: RequestContext):
        return await self._details.creator(request.handler_input)


class FollowCreator:
    """Alexa request/state/response adapter around the pure follow transition."""

    def __init__(self, user, feedback, events, play_followed) -> None:
        self._user = user
        self._feedback = feedback
        self._events = events
        self._play_followed = play_followed

    async def execute(self, request: RequestContext):
        handler_input = request.handler_input
        try:
            if AlexaRequest.wants_play_from_followed_creators(handler_input):
                return await self._play_followed(handler_input)
        except Exception:
            pass
        store = self._user.snapshot(handler_input)
        source = Social._follow_source(store) or {}
        creator_id = source.get("id")
        creator_name = source.get("name")
        source_type: Literal["creator", "organization"] = (
            "organization"
            if (source.get("kind") or source.get("type")) == "organization"
            else "creator"
        )
        if not creator_id or not creator_name or Speech.is_bad_credit(creator_name):
            return handler_input.response_builder.speak(Speech.NO_CREATOR_TO_FOLLOW).response
        if FollowingManager.is_following(store, creator_id, source_type):
            if store.get("awaitingFollow"):
                await self._feedback.clear(handler_input)
            else:
                audio_ctx = PlaybackContext.read_audio_player_context(handler_input)
                if not PlaybackContext.is_audio_player_active(audio_ctx):
                    return await self._play_followed(handler_input)
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(Speech.ALREADY_FOLLOWING(creator_name))
                )
                .reprompt(Ssml.ssml(Speech.IDLE_NEXT_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        try:
            command = FollowCommand(creator_id, creator_name, source_type)
            followed, receipt = FollowingManager.add(store.get("followedCreators"), command)
            self._user.update(handler_input, {"followedCreators": followed})
            if request.alexa_user_id:
                self._events.following(
                    handler_input=handler_input,
                    followed=True,
                    alexa_user_id=request.alexa_user_id,
                    listener_id=store.get("listenerId"),
                    source=receipt.command.event_source(),
                )
            if store.get("awaitingFollow"):
                await self._feedback.clear(handler_input)
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.FOLLOW_CREATOR(creator_name),
                Speech.FOLLOW_CREATOR_REPROMPT,
            )
        except Exception as exc:
            ApplicationLog.warning("Follow creator error=%s", type(exc).__name__)
            return (
                handler_input.response_builder.speak(Speech.ERROR_GENERIC)
                .reprompt(Speech.WELCOME_REPROMPT)
                .set_should_end_session(False)
                .response
            )


class UnfollowCreator:
    """Alexa request/state/response adapter around the pure unfollow transition."""

    def __init__(self, user, events) -> None:
        self._user = user
        self._events = events

    async def execute(self, request: RequestContext):
        handler_input = request.handler_input
        store = self._user.snapshot(handler_input)
        source = Social._follow_source(store) or {}
        creator_id = source.get("id")
        creator_name = source.get("name")
        source_type: Literal["creator", "organization"] = (
            "organization"
            if (source.get("kind") or source.get("type")) == "organization"
            else "creator"
        )
        if not creator_id or not creator_name:
            return handler_input.response_builder.speak(Speech.NO_CREATOR_TO_FOLLOW).response
        if not FollowingManager.is_following(store, creator_id, source_type):
            return handler_input.response_builder.speak(Speech.NOT_FOLLOWING(creator_name)).response
        try:
            command = FollowCommand(creator_id, creator_name, source_type)
            followed, receipt = FollowingManager.remove(store.get("followedCreators"), command)
            self._user.update(handler_input, {"followedCreators": followed})
            if request.alexa_user_id:
                self._events.following(
                    handler_input=handler_input,
                    followed=False,
                    alexa_user_id=request.alexa_user_id,
                    listener_id=store.get("listenerId"),
                    source=receipt.command.event_source(),
                )
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(Speech.UNFOLLOW_CREATOR(creator_name))
                )
                .reprompt(Ssml.ssml(Speech.IDLE_DO_NEXT_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        except Exception as exc:
            ApplicationLog.warning("Unfollow creator error=%s", type(exc).__name__)
            return (
                handler_input.response_builder.speak(Speech.ERROR_GENERIC)
                .reprompt(Speech.WELCOME_REPROMPT)
                .set_should_end_session(False)
                .response
            )
