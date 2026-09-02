from __future__ import annotations

from src.alexa.speech import Speech
from src.alexa.ssml import Ssml


class AlexaFeedback:
    @staticmethod
    def present_requested_feedback(handler_input):
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.RATE_CONTENT_PROMPT))
            .reprompt(Ssml.ssml(Speech.RATE_CONTENT_PROMPT))
            .with_should_end_session(False)
            .get_response()
        )

    @staticmethod
    def present_pending_feedback(handler_input, store: dict):
        pending = store.get("pendingFeedback") or {}
        title = (
            Speech.humanize_spoken_title(pending.get("title") or store.get("feedbackContentTitle"))
            or "that track"
        )
        creator_name = (
            pending.get("organizationName")
            or pending.get("creatorName")
            or store.get("feedbackCreator")
        )
        creator = Speech.escape_ssml_lite(creator_name) if creator_name else "the creator"
        user_name = store.get("userName") or store.get("givenName") or store.get("fullName")
        if pending.get("subjectType") == "publication":
            speech = f"You listened to {Speech.escape_ssml_lite(title)}. Did you enjoy this publication? Say enjoyed, it was okay, not enjoyed, or skip."
        else:
            speech = Speech.LAUNCH_PENDING_FEEDBACK(title, creator, user_name)
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Ssml.ssml(Speech.FEEDBACK_AWAITING_REPROMPT))
            .with_should_end_session(False)
            .get_response()
        )
