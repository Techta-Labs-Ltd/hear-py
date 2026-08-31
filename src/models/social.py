from __future__ import annotations

import logging

from ask_sdk_core.handler_input import HandlerInput

from src.alexa.playback_context import PlaybackContext
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.user import User
from src.utils.content import ContentUtils


class FollowingManager:
    __slots__ = ()

    @staticmethod
    def add(handler_input, source_id: str, source_name: str, source_type: str = "creator") -> dict:
        store = User.snapshot(handler_input)
        followed = list(store.get("followedCreators") or [])
        source_type = "organization" if source_type == "organization" else "creator"
        if any(
            (c.get("id") == source_id and c.get("type", "creator") == source_type for c in followed)
        ):
            return store
        followed.append({"id": source_id, "name": source_name, "type": source_type})
        return User.update(handler_input, {"followedCreators": followed})

    @staticmethod
    def remove(handler_input, source_id: str, source_type: str = "creator") -> dict:
        store = User.snapshot(handler_input)
        followed = [
            c
            for c in store.get("followedCreators") or []
            if not (c.get("id") == source_id and c.get("type", "creator") == source_type)
        ]
        return User.update(handler_input, {"followedCreators": followed})

    @staticmethod
    def is_following(store: dict, source_id: str, source_type: str = "creator") -> bool:
        return any(
            (
                c.get("id") == source_id and c.get("type", "creator") == source_type
                for c in store.get("followedCreators") or []
            )
        )


class ListeningTracker:
    __slots__ = ()

    @staticmethod
    def _normalize_creator(store: dict, creator) -> str | None:
        if not creator:
            return None
        raw = str(creator).strip()
        if not raw:
            return None
        if not ContentUtils.is_bad_credit_name(raw) and (not ContentUtils.is_id_like_label(raw)):
            return raw
        creator_id = store.get("feedbackCreatorId") or store.get("currentCreatorId") or None
        if creator_id and str(creator_id) == raw:
            name = store.get("feedbackCreator") or store.get("currentCreator") or None
            if (
                name
                and (not ContentUtils.is_bad_credit_name(name))
                and (not ContentUtils.is_id_like_label(name))
            ):
                return str(name).strip()
        for followed in store.get("followedCreators") or []:
            if followed.get("id") == raw:
                name = followed.get("name")
                if name and (not ContentUtils.is_bad_credit_name(name)):
                    return str(name).strip()
        return None

    @staticmethod
    def record(
        handler_input,
        *,
        category: str | None = None,
        creator: str | None = None,
        liked: bool | None = None,
    ) -> dict:
        store = User.snapshot(handler_input)
        pattern = dict(store.get("listeningPattern") or {})
        score = 2 if liked is True else -1 if liked is False else 1
        if category:
            key = f"category:{category}"
            pattern[key] = (pattern.get(key) or 0) + score
        creator_label = ListeningTracker._normalize_creator(store, creator)
        if creator_label:
            key = f"creator:{creator_label}"
            pattern[key] = (pattern.get(key) or 0) + score
        return User.update(handler_input, {"listeningPattern": pattern})


class CreatorIdentity:
    def __init__(self, *, deps: object | None = None):
        self._deps = Social._dependencies(deps)

    "Tells the user who the creator of the currently playing content is."

    def execute(self, handler_input: HandlerInput):
        store = User.snapshot(handler_input)
        title = store.get("currentContentTitle") or store.get("feedbackContentTitle")
        creator = store.get("currentCreator") or store.get("feedbackCreator")
        if not title:
            return handler_input.response_builder.speak(Speech.CREATOR_CREDIT_UNKNOWN).response
        if creator:
            return handler_input.response_builder.speak(
                Speech.CREATOR_CREDIT(title, creator)
            ).response
        return handler_input.response_builder.speak(Speech.CREATOR_CREDIT_UNKNOWN).response


class FollowCreator:
    def __init__(self, *, deps: object | None = None):
        self._deps = Social._dependencies(deps)

    "Follows the currently playing creator."

    async def execute(self, handler_input: HandlerInput):
        try:
            if AlexaRequest.wants_play_from_followed_creators(handler_input):
                return await self._deps.search.play_from_followed_creators(
                    handler_input, deps=self._deps
                )
        except Exception:
            pass
        store = User.snapshot(handler_input)
        source = Social._follow_source(store) or {}
        creator_id = source.get("id")
        creator_name = source.get("name")
        source_type = source.get("kind") or source.get("type") or "creator"
        if not creator_id or not creator_name or Speech.is_bad_credit(creator_name):
            return handler_input.response_builder.speak(Speech.NO_CREATOR_TO_FOLLOW).response
        if FollowingManager.is_following(store, creator_id, source_type):
            if store.get("awaitingFollow"):
                await self._deps.feedback.clear(handler_input)
            else:
                audio_ctx = PlaybackContext.read_audio_player_context(handler_input)
                if not PlaybackContext.is_audio_player_active(audio_ctx):
                    return await self._deps.search.play_from_followed_creators(
                        handler_input, deps=self._deps
                    )
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(Speech.ALREADY_FOLLOWING(creator_name))
                )
                .reprompt(Ssml.ssml(Speech.IDLE_NEXT_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        try:
            FollowingManager.add(handler_input, creator_id, creator_name, source_type)
            user_id = AlexaRequest.get_user_id(handler_input)
            if user_id:
                self._deps.events.following(
                    followed=True,
                    alexa_user_id=user_id,
                    listener_id=store.get("listenerId"),
                    source={
                        "id": creator_id,
                        "name": creator_name,
                        "type": source_type,
                    },
                )
            if store.get("awaitingFollow"):
                await self._deps.feedback.clear(handler_input)
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.FOLLOW_CREATOR(creator_name),
                Speech.FOLLOW_CREATOR_REPROMPT,
            )
        except Exception as err:
            Social.logger.warning("Follow creator error: %s", err)
            return (
                handler_input.response_builder.speak(Speech.ERROR_GENERIC)
                .reprompt(Speech.WELCOME_REPROMPT)
                .set_should_end_session(False)
                .response
            )


class UnfollowCreator:
    def __init__(self, *, deps: object | None = None):
        self._deps = Social._dependencies(deps)

    "Unfollows the currently playing creator."

    async def execute(self, handler_input: HandlerInput):
        store = User.snapshot(handler_input)
        source = Social._follow_source(store) or {}
        creator_id = source.get("id")
        creator_name = source.get("name")
        source_type = source.get("kind") or source.get("type") or "creator"
        if not creator_id or not creator_name:
            return handler_input.response_builder.speak(Speech.NO_CREATOR_TO_FOLLOW).response
        if not FollowingManager.is_following(store, creator_id, source_type):
            return handler_input.response_builder.speak(Speech.NOT_FOLLOWING(creator_name)).response
        try:
            FollowingManager.remove(handler_input, creator_id, source_type)
            user_id = AlexaRequest.get_user_id(handler_input)
            if user_id:
                self._deps.events.following(
                    followed=False,
                    alexa_user_id=user_id,
                    listener_id=store.get("listenerId"),
                    source={
                        "id": creator_id,
                        "name": creator_name,
                        "type": source_type,
                    },
                )
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(Speech.UNFOLLOW_CREATOR(creator_name))
                )
                .reprompt(Ssml.ssml(Speech.IDLE_DO_NEXT_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        except Exception as err:
            Social.logger.warning("Unfollow creator error: %s", err)
            return (
                handler_input.response_builder.speak(Speech.ERROR_GENERIC)
                .reprompt(Speech.WELCOME_REPROMPT)
                .set_should_end_session(False)
                .response
            )


class Social:
    logger = logging.getLogger(__name__)

    @staticmethod
    def _dependencies(deps: object | None):
        if deps is None:
            raise RuntimeError("Social requires injected dependencies")
        return deps

    @staticmethod
    def _follow_source(store: dict) -> dict | None:
        pending = store.get("pendingFollowSource")
        if isinstance(pending, dict) and pending.get("id") and pending.get("name"):
            return pending
        playback = store.get("activePlayback") or {}
        source = ContentUtils.pick_content_source(
            {
                "organizationId": playback.get("organizationId")
                or store.get("currentOrganizationId"),
                "organizationName": playback.get("organizationName")
                or store.get("currentOrganization"),
                "creatorId": playback.get("creatorId")
                or store.get("currentCreatorId")
                or store.get("feedbackCreatorId"),
                "creatorName": playback.get("creatorName")
                or store.get("currentCreator")
                or store.get("feedbackCreator"),
            }
        )
        return source
