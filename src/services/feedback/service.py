from __future__ import annotations

from src.services.storage.persistence import get_store, update_store
from src.utils.skill_request import get_intent_name, get_request_type
from src.utils.speech import (
    FEEDBACK_AWAITING_REPROMPT,
    LAUNCH_PENDING_FEEDBACK,
    escape_ssml_lite,
    humanize_spoken_title,
    ssml,
)


class FeedbackService:
    rating_intents = {
        "FeedbackEnjoyedIntent",
        "FeedbackSomewhatIntent",
        "FeedbackNotEnjoyedIntent",
        "SkipFeedbackIntent",
    }
    replay_intents = {"AMAZON.RepeatIntent", "AMAZON.StartOverIntent"}
    follow_intents = {"FollowCreatorIntent", "UnfollowCreatorIntent"}
    notification_intents = {
        "EnableNotificationsIntent",
        "DisableNotificationsIntent",
    }
    report_intents = {"ReportCreatorIntent", "ReportContentIntent"}

    def should_evaluate(self, handler_input) -> bool:
        request_type = get_request_type(handler_input)
        if request_type.startswith("AudioPlayer."):
            return False
        if request_type == "SessionEndedRequest":
            return False
        if request_type == "IntentRequest" and get_intent_name(handler_input) in {
            "AMAZON.StopIntent",
            "AMAZON.CancelIntent",
        }:
            return False
        return get_store(handler_input).get("onboardingStage") != "ask_town"

    def should_block(self, handler_input) -> bool:
        if not self.should_evaluate(handler_input):
            return False
        store = get_store(handler_input)
        if not store.get("awaitingFeedback"):
            self.clear_stale_state(handler_input)
            return False
        if get_request_type(handler_input) != "IntentRequest":
            return True
        intent_name = get_intent_name(handler_input)
        allowed = (
            self.rating_intents
            | self.replay_intents
            | self.report_intents
            | {"AMAZON.YesIntent", "AMAZON.NoIntent"}
        )
        return intent_name not in allowed

    def clear_stale_state(self, handler_input) -> None:
        if get_request_type(handler_input) != "IntentRequest":
            return
        store = get_store(handler_input)
        intent_name = get_intent_name(handler_input)

        if store.get("awaitingFollow"):
            if intent_name not in self.follow_intents | {"AMAZON.NoIntent"}:
                update_store(handler_input, {"awaitingFollow": False})
            return

        if store.get("awaitingNotificationOptIn"):
            allowed = self.notification_intents | {
                "AMAZON.YesIntent",
                "AMAZON.NoIntent",
            }
            if intent_name not in allowed:
                update_store(handler_input, {"awaitingNotificationOptIn": False})
            return

        if store.get("awaitingReportDecision"):
            allowed = self.report_intents | {
                "SkipFeedbackIntent",
                "AMAZON.NoIntent",
            }
            if intent_name not in allowed:
                update_store(handler_input, {"awaitingReportDecision": False})

    def pending_response(self, handler_input):
        store = get_store(handler_input)
        pending = store.get("pendingFeedback") or {}
        title = humanize_spoken_title(
            pending.get("title") or store.get("feedbackContentTitle")
        ) or "that track"
        creator_name = pending.get("creatorName") or store.get("feedbackCreator")
        creator = (
            escape_ssml_lite(creator_name)
            if creator_name
            else "the creator"
        )
        user_name = (
            store.get("userName")
            or store.get("givenName")
            or store.get("fullName")
        )
        return (
            handler_input.response_builder
            .speak(ssml(LAUNCH_PENDING_FEEDBACK(title, creator, user_name)))
            .reprompt(ssml(FEEDBACK_AWAITING_REPROMPT))
            .with_should_end_session(False)
            .get_response()
        )


feedback_service = FeedbackService()
