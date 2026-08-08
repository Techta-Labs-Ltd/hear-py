from __future__ import annotations
from src.services.store import get_store, update_store
from src.utils.skill_request import get_intent_name, get_request_type
from src.utils.speech import (
    FEEDBACK_AWAITING_REPROMPT,
    LAUNCH_PENDING_FEEDBACK,
    escape_ssml_lite,
    humanize_spoken_title,
    ssml,
)
import time
from src.services.dialog_state import activate_dialog
from src.clients.alexa import cancel_feedback_reminder


class FeedbackService:
    rating_intents = {
        "FeedbackEnjoyedIntent",
        "FeedbackSomewhatIntent",
        "FeedbackNotEnjoyedIntent",
        "SkipFeedbackIntent",
    }
    replay_intents = {"AMAZON.RepeatIntent", "AMAZON.StartOverIntent"}
    follow_intents = {"FollowCreatorIntent", "UnfollowCreatorIntent"}
    report_intents = {"ReportCreatorIntent", "ReportContentIntent"}
    transport_intents = {
        "AMAZON.NextIntent",
        "AMAZON.SkipIntent",
        "AMAZON.PreviousIntent",
        "AMAZON.PauseIntent",
        "AMAZON.ResumeIntent",
    }
    transport_request_types = {
        "PlaybackController.NextCommandIssued",
        "PlaybackController.PreviousCommandIssued",
        "PlaybackController.PauseCommandIssued",
        "PlaybackController.PlayCommandIssued",
    }

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
        request_type = get_request_type(handler_input)
        if request_type in self.transport_request_types:
            return False
        store = get_store(handler_input)
        pending = store.get("pendingFeedback") or {}
        if store.get("awaitingFeedback") and pending.get("completed") is False:
            update_store(handler_input, {
                "pendingFeedback": None,
                "awaitingFeedback": False,
                "activeDialog": None,
            })
            return False
        if not store.get("awaitingFeedback"):
            self.clear_stale_state(handler_input)
            return False
        if request_type != "IntentRequest":
            return True
        intent_name = get_intent_name(handler_input)
        allowed = (
            self.rating_intents
            | self.replay_intents
            | self.report_intents
            | self.transport_intents
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
        if store.get("awaitingReportDecision"):
            allowed = self.report_intents | {"SkipFeedbackIntent", "AMAZON.NoIntent"}
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

    # ---------------------------------------------------------- static helpers

    @staticmethod
    def _feedback_key(state: dict) -> str | None:
        return state.get("contentId")

    @staticmethod
    def record_candidate(handler_input, state: dict, *, completed: bool) -> dict | None:
        if not completed:
            return None
        key = FeedbackService._feedback_key(state)
        listened_ms = max(0, int(state.get("listenedMs") or 0))
        if not key:
            return None
        store = get_store(handler_input)
        if key in (store.get("answeredFeedbackKeys") or []):
            return None
        candidate = {
            "feedbackKey": key,
            "contentId": state.get("contentId"),
            "publicationId": state.get("publicationId"),
            "title": state.get("title") or state.get("publicationTitle"),
            "publicationTitle": state.get("publicationTitle"),
            "creatorId": state.get("creatorId"),
            "creatorName": state.get("creatorName"),
            "category": state.get("category"),
            "listenedMs": listened_ms,
            "completed": bool(completed),
            "sessionId": state.get("sessionId"),
            "createdAt": int(time.time() * 1000),
        }
        existing = [
            value for value in (store.get("feedbackCandidates") or [])
            if value.get("feedbackKey") != key
        ]
        update_store(handler_input, {"feedbackCandidates": (existing + [candidate])[-20:]})
        return candidate

    @staticmethod
    def activate_best(handler_input) -> dict | None:
        store = get_store(handler_input)
        if store.get("awaitingFeedback"):
            return store.get("pendingFeedback")
        candidates = [
            item for item in (store.get("feedbackCandidates") or [])
            if item.get("completed") is True
            if item.get("feedbackKey") not in (store.get("answeredFeedbackKeys") or [])
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (
                bool(item.get("completed")),
                int(item.get("listenedMs") or 0),
                int(item.get("createdAt") or 0),
            ),
            reverse=True,
        )
        selected = candidates[0]
        session_id = selected.get("sessionId")
        remaining = [item for item in candidates if item.get("sessionId") != session_id]
        update_store(handler_input, {
            "pendingFeedback": selected,
            "feedbackCandidates": remaining,
            "awaitingFeedback": True,
            "_requiresReliableSave": True,
        })
        activate_dialog(handler_input, "feedback", context=selected)
        return selected

    @staticmethod
    def mark_answered(handler_input) -> dict:
        store = get_store(handler_input)
        pending = store.get("pendingFeedback") or {}
        key = pending.get("feedbackKey")
        answered = list(store.get("answeredFeedbackKeys") or [])
        if key and key not in answered:
            answered.append(key)
        return update_store(handler_input, {
            "answeredFeedbackKeys": answered[-100:],
            "pendingFeedback": None,
            "awaitingFeedback": False,
            "activeDialog": None,
            "_requiresReliableSave": False,
        })

    @staticmethod
    async def submit(handler_input, value: str) -> dict:
        del value
        return FeedbackService.mark_answered(handler_input)

    @staticmethod
    async def clear(handler_input) -> dict:
        try:
            await cancel_feedback_reminder(handler_input)
        except Exception:
            pass
        return update_store(handler_input, {
            "activeDialog": None,
            "awaitingFeedback": False,
            "awaitingFollow": False,
            "awaitingReportDecision": False,
            "reportContext": None,
            "pendingFeedback": None,
            "feedbackContentId": None,
            "feedbackPromptText": None,
            "feedbackCategory": None,
            "feedbackCreator": None,
            "feedbackCreatorId": None,
            "feedbackContentTitle": None,
            "feedbackReminderAlertToken": None,
            "feedbackAskedForToken": None,
            "playbackDurationEstimateMs": None,
        })

    @staticmethod
    def dismiss(handler_input) -> dict:
        return update_store(handler_input, {
            "awaitingFeedback": False,
            "pendingFeedback": None,
            "feedbackPromptText": None,
            "feedbackAskedForToken": None,
            "feedbackReminderAlertToken": None,
        })


feedback_service = FeedbackService()

record_feedback_candidate = feedback_service.record_candidate
activate_best_feedback_candidate = feedback_service.activate_best
mark_pending_feedback_answered = feedback_service.mark_answered
submit_feedback = feedback_service.submit
clear_feedback = feedback_service.clear
dismiss_feedback_prompt = feedback_service.dismiss
