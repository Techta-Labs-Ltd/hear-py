from __future__ import annotations

import logging
import time

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.services.storage.persistence import (
    get_store, update_store, is_following, add_followed_creator,
    remove_followed_creator, clear_feedback,
)
from src.utils.skill_request import get_request_type, get_intent_name, get_user_id as _get_user_id
from src.utils.speech import (
    ssml, escape_ssml_lite, is_bad_credit, CREATOR_CREDIT, CREATOR_CREDIT_UNKNOWN,
    NO_CREATOR_TO_FOLLOW, ALREADY_FOLLOWING, IDLE_NEXT_REPROMPT, FOLLOW_CREATOR,
    FOLLOW_CREATOR_REPROMPT, FOLLOW_CREATOR_ASK_NOTIFICATIONS,
    FOLLOW_CREATOR_NOTIFICATION_REPROMPT, NOT_FOLLOWING, UNFOLLOW_CREATOR,
    IDLE_DO_NEXT_REPROMPT, REPORT_NOTHING_PLAYING, REPORT_CONTENT_THEN_ASK_CONTINUE,
    FLAGGED_CONTINUE_REPROMPT, REPORT_CREATOR_CONFIRM, CONTENT_ABOUT_PHRASE,
    ERROR_GENERIC, WELCOME_REPROMPT, NOTIFICATIONS_ENABLE_FAILED,
)
from src.utils.feedback_flow import idle_next_response
from src.utils.playback_context import (
    read_audio_player_context, is_audio_player_active,
    build_report_context,
)
from src.handlers.notifications import has_notification_permission, complete_notification_opt_in
from src.handlers.intents.play import play_from_followed_creators
from src.utils.search_filters import wants_play_from_followed_creators
from src.services.outbound_dispatch import dispatch
from src.services.deferred_intent import has_deferred_intent, resume_deferred_intent
from src.services.dialog_state import clear_active_dialog

logger = logging.getLogger(__name__)



def _current_timestamp_ms() -> int:
    """Return current UTC time in milliseconds."""
    return int(time.time() * 1000)


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
    """Follows the currently playing creator and optionally enables notifications."""

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
        creator_id = store.get("currentCreatorId") or store.get("feedbackCreatorId")
        creator_name = store.get("currentCreator") or store.get("feedbackCreator")

        if not creator_id or not creator_name or is_bad_credit(creator_name):
            return handler_input.response_builder \
                .speak(NO_CREATOR_TO_FOLLOW) \
                .response

        if is_following(store, creator_id):
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

        user_id = _get_user_id(handler_input)
        try:
            dispatch("user.followed_creator", {
                "userId": user_id, "listenerId": store.get("listenerId"),
                "creatorId": creator_id, "creatorName": creator_name,
                "timestamp": _current_timestamp_ms(),
            }, {"awaitQueue": True})

            add_followed_creator(handler_input, creator_id, creator_name)
            if store.get("awaitingFollow"):
                await clear_feedback(handler_input)

            has_perm = has_notification_permission(handler_input)

            if has_perm:
                result = await complete_notification_opt_in(handler_input)
                if result.get("ok"):
                    return idle_next_response(
                        handler_input,
                        FOLLOW_CREATOR(creator_name),
                        FOLLOW_CREATOR_REPROMPT,
                    )
                return idle_next_response(
                    handler_input,
                    f"Done! You're now following {escape_ssml_lite(creator_name)}. {NOTIFICATIONS_ENABLE_FAILED}",
                    FOLLOW_CREATOR_REPROMPT,
                )

            update_store(handler_input, {"awaitingNotificationOptIn": True})
            return handler_input.response_builder \
                .speak(ssml(FOLLOW_CREATOR_ASK_NOTIFICATIONS(creator_name))) \
                .reprompt(ssml(FOLLOW_CREATOR_NOTIFICATION_REPROMPT)) \
                .set_should_end_session(False) \
                .response
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
        creator_id = store.get("currentCreatorId") or store.get("feedbackCreatorId")
        creator_name = store.get("currentCreator") or store.get("feedbackCreator")

        if not creator_id or not creator_name:
            return handler_input.response_builder \
                .speak(NO_CREATOR_TO_FOLLOW) \
                .response

        if not is_following(store, creator_id):
            return handler_input.response_builder \
                .speak(NOT_FOLLOWING(creator_name)) \
                .response

        user_id = _get_user_id(handler_input)
        try:
            dispatch("user.unfollowed_creator", {
                "userId": user_id, "listenerId": store.get("listenerId"),
                "creatorId": creator_id, "timestamp": _current_timestamp_ms(),
            }, {"awaitQueue": True})
            remove_followed_creator(handler_input, creator_id)
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


class ReportContentHandler(AbstractRequestHandler):
    """Flags the currently playing content for review."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "ReportContentIntent"
        )

    async def handle(self, handler_input: HandlerInput):

        store = get_store(handler_input)
        audio = read_audio_player_context(handler_input)
        report = build_report_context(
            store,
            audio_token=audio.get("token") if audio else None,
        )
        content_id = report.get("contentId")
        title = report.get("title")
        creator_id = report.get("creatorId")

        if not content_id:
            logger.warning(
                "Hear: report content blocked contentId=%s", content_id,
            )
            return handler_input.response_builder \
                .speak(REPORT_NOTHING_PLAYING) \
                .response

        user_id = _get_user_id(handler_input)
        locale = None
        device_id = None
        try:
            locale = handler_input.request_envelope.request.locale
            device_id = handler_input.request_envelope.context.System.device.deviceId
        except Exception:
            pass

        try:
            dispatch("user.reported_content", {
                "userId": user_id, "listenerId": store.get("listenerId"),
                "contentId": content_id,
                "reason": "reported_via_alexa", "title": title,
                "creatorId": creator_id, "locale": locale, "deviceId": device_id,
                "clientEventId": f"alexa-report:{user_id}:{content_id}",
                "timestamp": _current_timestamp_ms(),
            }, {"awaitQueue": True})
            update_store(handler_input, {
                "awaitingReportDecision": False,
                "reportContext": None,
            })
            clear_active_dialog(handler_input, "report_decision")
            if has_deferred_intent(handler_input):
                return await resume_deferred_intent(handler_input)
            update_store(handler_input, {"awaitingContinueAfterFlag": True})
            return handler_input.response_builder \
                .speak(ssml(REPORT_CONTENT_THEN_ASK_CONTINUE)) \
                .reprompt(FLAGGED_CONTINUE_REPROMPT) \
                .set_should_end_session(False) \
                .response
        except Exception as err:
            logger.warning("Report content error: %s", err)
            return handler_input.response_builder \
                .speak(ERROR_GENERIC) \
                .reprompt(WELCOME_REPROMPT) \
                .set_should_end_session(False) \
                .response


class ReportCreatorHandler(AbstractRequestHandler):
    """Flags the currently playing content's creator for review."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "ReportCreatorIntent"
        )

    async def handle(self, handler_input: HandlerInput):

        store = get_store(handler_input)
        creator_id = store.get("currentCreatorId") or store.get("feedbackCreatorId")
        creator_name = store.get("currentCreator") or store.get("feedbackCreator")

        if not creator_id:
            return handler_input.response_builder \
                .speak(REPORT_NOTHING_PLAYING) \
                .response

        user_id = _get_user_id(handler_input)
        try:
            dispatch("user.reported_creator", {
                "userId": user_id, "listenerId": store.get("listenerId"),
                "creatorId": creator_id, "reason": "reported_via_alexa",
                "timestamp": _current_timestamp_ms(),
            }, {"awaitQueue": True})
            await clear_feedback(handler_input)

            confirm = REPORT_CREATOR_CONFIRM(creator_name) \
                if (creator_name and not is_bad_credit(creator_name)) \
                else "Thank you. We've flagged that creator's content for review. What would you like to listen to next?"

            return idle_next_response(handler_input, confirm)
        except Exception as err:
            logger.warning("Report creator error: %s", err)
            return handler_input.response_builder \
                .speak(ERROR_GENERIC) \
                .reprompt(WELCOME_REPROMPT) \
                .set_should_end_session(False) \
                .response



class WhatsThisAboutHandler(AbstractRequestHandler):
    """Describes what the currently playing content is about."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "WhatsThisAboutIntent"
        )

    async def handle(self, handler_input: HandlerInput):

        store = get_store(handler_input)
        summary = store.get("currentSummary")
        title = store.get("currentContentTitle") or store.get("feedbackContentTitle")
        creator = store.get("currentCreator") or store.get("feedbackCreator")

        if creator and is_bad_credit(creator):
            creator = None

        phrase = CONTENT_ABOUT_PHRASE(title, summary, None, creator)
        return handler_input.response_builder \
            .speak(ssml(phrase)) \
            .response
