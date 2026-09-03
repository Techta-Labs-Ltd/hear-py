from __future__ import annotations

from src.alexa.speech import Speech
from src.alexa.ssml import Ssml


class AlexaFeedback:
    @staticmethod
    def subject_title(subject: dict | None, store: dict | None = None) -> str:
        current = subject if isinstance(subject, dict) else {}
        saved = store if isinstance(store, dict) else {}
        active = saved.get("activePlayback") or {}
        queue = saved.get("playbackQueue") or {}
        has_current_identity = bool(
            current.get("feedbackKey")
            or current.get("subjectType")
            or current.get("publicationId")
            or current.get("contentId")
        )
        is_publication = (
            bool(
                current.get("subjectType") == "publication"
                or current.get("publicationId")
            )
            if has_current_identity
            else bool(
                active.get("subjectType") == "publication"
                or active.get("publicationId")
            )
        )
        active_matches = not has_current_identity or (
            str(active.get("publicationId") or active.get("contentId") or "")
            == str(current.get("publicationId") or current.get("contentId") or "")
        )
        queue_matches = not current.get("publicationId") or (
            str(queue.get("publicationId") or "")
            == str(current.get("publicationId") or "")
        )
        candidates = (
            (
                current.get("publicationTitle"),
                current.get("subjectTitle"),
                active.get("publicationTitle") if active_matches else None,
                active.get("subjectTitle") if active_matches else None,
                queue.get("publicationTitle") if queue_matches else None,
                current.get("title"),
                saved.get("feedbackContentTitle"),
            )
            if is_publication
            else (
                current.get("title"),
                current.get("subjectTitle"),
                active.get("title") if active_matches else None,
                active.get("subjectTitle") if active_matches else None,
                saved.get("feedbackContentTitle"),
                saved.get("currentContentTitle"),
            )
        )
        for candidate in candidates:
            title = Speech.humanize_spoken_title(candidate)
            if title:
                return title
        return "this publication" if is_publication else "this recording"

    @staticmethod
    def feedback_question(title: str) -> str:
        return f"Did you enjoy {Speech.escape_ssml_lite(title)}? Say enjoyed, it was okay, not enjoyed, or skip."

    @staticmethod
    def resuming_speech(subject: dict | None, store: dict, *, skipped: bool = False) -> str:
        title = Speech.escape_ssml_lite(AlexaFeedback.subject_title(subject, store))
        prefix = "No problem." if skipped else "Thanks for the feedback."
        return f"{prefix} Resuming {title}."

    @staticmethod
    def keep_listening_question(subject: dict | None, store: dict) -> str:
        title = Speech.escape_ssml_lite(AlexaFeedback.subject_title(subject, store))
        return f"Do you want to keep listening to {title}? Say yes to continue, or no to skip to something else."

    @staticmethod
    def keep_listening_reprompt(subject: dict | None, store: dict) -> str:
        title = Speech.escape_ssml_lite(AlexaFeedback.subject_title(subject, store))
        return f"Say yes to keep listening to {title}, or no to skip to the next item."

    @staticmethod
    def continuing_speech(subject: dict | None, store: dict) -> str:
        title = Speech.escape_ssml_lite(AlexaFeedback.subject_title(subject, store))
        return f"Okay, continuing {title}."

    @staticmethod
    def present_requested_feedback(
        handler_input,
        stop_directive: dict,
        pending: dict,
        store: dict,
    ):
        prompt = AlexaFeedback.feedback_question(
            AlexaFeedback.subject_title(pending, store)
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(prompt))
            .reprompt(Ssml.ssml(prompt))
            .add_directive(stop_directive)
            .with_should_end_session(False)
            .get_response()
        )

    @staticmethod
    def present_pending_feedback(handler_input, store: dict):
        pending = store.get("pendingFeedback") or {}
        title = AlexaFeedback.subject_title(pending, store)
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
            .reprompt(Ssml.ssml(AlexaFeedback.feedback_question(title)))
            .with_should_end_session(False)
            .get_response()
        )
