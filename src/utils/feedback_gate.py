from __future__ import annotations

import time
import uuid

from src.services.persistence import get_store, update_store
from src.utils.feedback_advance import advance_after_negative_feedback
from src.utils.feedback_flow import idle_next_response
from src.utils.speech import ssml, escape_ssml_lite, humanize_spoken_title, LAUNCH_PENDING_FEEDBACK, FEEDBACK_AWAITING_REPROMPT
from src.utils.skill_request import get_request_type, get_intent_name

FEEDBACK_RATING_INTENTS = {
    "FeedbackEnjoyedIntent", "FeedbackSomewhatIntent",
    "FeedbackNotEnjoyedIntent", "SkipFeedbackIntent",
}

REPLAY_INTENTS = {"AMAZON.RepeatIntent", "AMAZON.StartOverIntent"}
FOLLOW_INTENTS = {"FollowCreatorIntent", "UnfollowCreatorIntent"}
NOTIFICATION_INTENTS = {"EnableNotificationsIntent", "DisableNotificationsIntent"}
REPORT_INTENTS = {"ReportCreatorIntent", "ReportContentIntent"}


def _clear_stale_notification_opt_in(handler_input):
    update_store(handler_input, {"awaitingNotificationOptIn": False})


def pending_feedback_response(handler_input, store: dict):
    """Build a response prompting the user to complete pending feedback."""
    pf = store.get("pendingFeedback") or {}
    title = humanize_spoken_title(pf.get("title") or store.get("feedbackContentTitle")) or "that track"
    creator_raw = pf.get("creatorName") or store.get("feedbackCreator")
    creator = escape_ssml_lite(creator_raw) if creator_raw else "the creator"
    user_name = store.get("userName") or store.get("givenName") or store.get("fullName") or None
    return handler_input.response_builder \
        .speak(ssml(LAUNCH_PENDING_FEEDBACK(title, creator, user_name))) \
        .reprompt(ssml(FEEDBACK_AWAITING_REPROMPT)) \
        .with_should_end_session(False) \
        .get_response()


def block_if_awaiting_feedback(handler_input):
    """Block interaction if the session is awaiting user feedback rating."""
    store = get_store(handler_input)
    if not store.get("awaitingFeedback"):
        return None
    request_type = get_request_type(handler_input)
    intent_name = get_intent_name(handler_input)
    if request_type == "IntentRequest":
        if intent_name in FEEDBACK_RATING_INTENTS:
            return None
        if intent_name in ("AMAZON.YesIntent", "AMAZON.NoIntent"):
            return None
        if intent_name in REPLAY_INTENTS:
            return None
    return pending_feedback_response(handler_input, store)


def enforce_interaction_gate(handler_input):
    """Enforce all interaction gates (feedback, follow, notification, report) and clear stale states."""
    request_type = get_request_type(handler_input)
    if request_type != "IntentRequest":
        return None
    store = get_store(handler_input)
    intent_name = get_intent_name(handler_input)

    if store.get("awaitingFeedback"):
        if intent_name in FEEDBACK_RATING_INTENTS:
            return None
        if intent_name in ("AMAZON.YesIntent", "AMAZON.NoIntent"):
            return None
        if intent_name in REPLAY_INTENTS:
            return None
        update_store(handler_input, {"awaitingFeedback": False})
        return None

    if store.get("awaitingFollow"):
        if intent_name in FOLLOW_INTENTS or intent_name == "AMAZON.NoIntent":
            return None
        update_store(handler_input, {"awaitingFollow": False})
        return None

    if store.get("awaitingNotificationOptIn"):
        if intent_name in ("AMAZON.YesIntent", "AMAZON.NoIntent") or intent_name in NOTIFICATION_INTENTS:
            return None
        _clear_stale_notification_opt_in(handler_input)
        return None

    if store.get("awaitingReportDecision"):
        if intent_name in REPORT_INTENTS or intent_name == "SkipFeedbackIntent" or intent_name == "AMAZON.NoIntent":
            return None
        update_store(handler_input, {"awaitingReportDecision": False})
        return None

    return None
