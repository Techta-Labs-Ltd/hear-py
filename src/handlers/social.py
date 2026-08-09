from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from src.services.feedback import clear_feedback
from src.services.following import (
    is_following,
    add_followed_creator,
    remove_followed_creator,
)
from src.services.store import get_store
from src.utils.skill_request import (
    get_request_type,
    get_intent_name,
)
from src.utils.speech import (
    ssml,
    is_bad_credit,
    CREATOR_CREDIT,
    CREATOR_CREDIT_UNKNOWN,
    NO_CREATOR_TO_FOLLOW,
    ALREADY_FOLLOWING,
    IDLE_NEXT_REPROMPT,
    FOLLOW_CREATOR,
    FOLLOW_CREATOR_REPROMPT,
    NOT_FOLLOWING,
    UNFOLLOW_CREATOR,
    IDLE_DO_NEXT_REPROMPT,
    ERROR_GENERIC,
    WELCOME_REPROMPT,
)
from src.utils.feedback_flow import idle_next_response
from src.utils.playback_context import read_audio_player_context, is_audio_player_active
from src.handlers.search import play_from_followed_creators
from src.utils.search_filters import wants_play_from_followed_creators
from src.utils.normalize_content_item import pick_content_source


def _follow_source(store: dict) -> dict | None:
    pending = store.get("pendingFollowSource")
    if isinstance(pending, dict) and pending.get("id") and pending.get("name"):
        return pending
    playback = store.get("activePlayback") or {}
    source = pick_content_source({
        "organizationId": playback.get("organizationId") or store.get("currentOrganizationId"),
        "organizationName": playback.get("organizationName") or store.get("currentOrganization"),
        "creatorId": playback.get("creatorId") or store.get("currentCreatorId") or store.get("feedbackCreatorId"),
        "creatorName": playback.get("creatorName") or store.get("currentCreator") or store.get("feedbackCreator"),
    })
    return source


class WhoIsCreatorHandler(AbstractRequestHandler):
    """Tells the user who the creator of the currently playing content is."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "WhoIsCreatorIntent"
        )

    def handle(self, handler_input: HandlerInput):

        store = get_store(handler_input)
        title = store.get("currentContentTitle") or store.get("feedbackContentTitle")
        creator = store.get("currentCreator") or store.get("feedbackCreator")

        if not title:
            return handler_input.response_builder \
                .speak(CREATOR_CREDIT_UNKNOWN) \
                .response

        if creator:
            return handler_input.response_builder \
                .speak(CREATOR_CREDIT(title, creator)) \
                .response

        return handler_input.response_builder \
            .speak(CREATOR_CREDIT_UNKNOWN) \
            .response


class FollowCreatorHandler(AbstractRequestHandler):
    """Follows the currently playing creator."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "FollowCreatorIntent"
        )

    async def handle(self, handler_input: HandlerInput):

        try:
            if wants_play_from_followed_creators(handler_input):
                return await play_from_followed_creators(handler_input)
        except Exception:
            pass

        store = get_store(handler_input)
        source = _follow_source(store) or {}
        creator_id = source.get("id")
        creator_name = source.get("name")
        source_type = source.get("kind") or source.get("type") or "creator"

        if not creator_id or not creator_name or is_bad_credit(creator_name):
            return handler_input.response_builder \
                .speak(NO_CREATOR_TO_FOLLOW) \
                .response

        if is_following(store, creator_id, source_type):
            if store.get("awaitingFollow"):
                await clear_feedback(handler_input)
            else:
                audio_ctx = read_audio_player_context(handler_input)
                if not is_audio_player_active(audio_ctx):
                    return await play_from_followed_creators(handler_input)
            return handler_input.response_builder \
                .speak(ssml(ALREADY_FOLLOWING(creator_name))) \
                .reprompt(ssml(IDLE_NEXT_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        try:
            add_followed_creator(handler_input, creator_id, creator_name, source_type)
            if store.get("awaitingFollow"):
                await clear_feedback(handler_input)

            return idle_next_response(
                handler_input,
                FOLLOW_CREATOR(creator_name),
                FOLLOW_CREATOR_REPROMPT,
            )
        except Exception as err:
            logger.warning("Follow creator error: %s", err)
            return handler_input.response_builder \
                .speak(ERROR_GENERIC) \
                .reprompt(WELCOME_REPROMPT) \
                .set_should_end_session(False) \
                .response


class UnfollowCreatorHandler(AbstractRequestHandler):
    """Unfollows the currently playing creator."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "UnfollowCreatorIntent"
        )

    async def handle(self, handler_input: HandlerInput):

        store = get_store(handler_input)
        source = _follow_source(store) or {}
        creator_id = source.get("id")
        creator_name = source.get("name")
        source_type = source.get("kind") or source.get("type") or "creator"

        if not creator_id or not creator_name:
            return handler_input.response_builder \
                .speak(NO_CREATOR_TO_FOLLOW) \
                .response

        if not is_following(store, creator_id, source_type):
            return handler_input.response_builder \
                .speak(NOT_FOLLOWING(creator_name)) \
                .response

        try:
            remove_followed_creator(handler_input, creator_id, source_type)
            return handler_input.response_builder \
                .speak(ssml(UNFOLLOW_CREATOR(creator_name))) \
                .reprompt(ssml(IDLE_DO_NEXT_REPROMPT)) \
                .set_should_end_session(False) \
                .response
        except Exception as err:
            logger.warning("Unfollow creator error: %s", err)
            return handler_input.response_builder \
                .speak(ERROR_GENERIC) \
                .reprompt(WELCOME_REPROMPT) \
                .set_should_end_session(False) \
                .response
