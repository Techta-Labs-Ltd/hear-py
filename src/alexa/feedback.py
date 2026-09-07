from __future__ import annotations

from src.alexa.discovery_speech import DiscoverySpeech
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.utils.content import ContentUtils


class AlexaFeedback:
    @staticmethod
    def normalize_value(value: object) -> str | None:
        text = " ".join(str(value or "").casefold().replace("’", "'").split())
        if not text:
            return None
        if text in {
            "skip",
            "skip it",
            "skip feedback",
            "skip this feedback",
            "skip rating",
            "skip the rating",
            "never mind",
            "ignore that",
            "pass",
            "no comment",
            "don't bother",
            "i don't want to rate",
            "i'd rather not say",
        }:
            return "skipped"
        if any(
            phrase in text
            for phrase in (
                "not enjoyed",
                "did not enjoy",
                "didn't enjoy",
                "did not like",
                "didn't like",
                "don't like",
                "not for me",
                "thumbs down",
                "one star",
                "was poor",
            )
        ):
            return "not enjoyed"
        if any(
            phrase in text
            for phrase in (
                "somewhat",
                "okay",
                "alright",
                "not bad",
                "fine",
                "could be better",
                "nothing special",
                "mixed feelings",
                "three stars",
            )
        ):
            return "somewhat"
        if any(
            phrase in text
            for phrase in (
                "enjoyed",
                "liked",
                "loved",
                "was good",
                "was great",
                "very good",
                "brilliant",
                "five stars",
                "thumbs up",
            )
        ):
            return "enjoyed"
        return None

    @staticmethod
    def _discovery_subject(current: dict, active: dict, queue: dict) -> str | None:
        discovery_context = (
            current.get("discoveryContext")
            or active.get("discoveryContext")
            or queue.get("discoveryContext")
        )
        return (
            ContentUtils.publication_title({"discoveryContext": discovery_context})
            if isinstance(discovery_context, dict)
            and discovery_context.get("kind") == "publication"
            else DiscoverySpeech.subject(discovery_context)
        )

    @staticmethod
    def _publication_identity(current: dict, active: dict) -> tuple[bool, bool]:
        has_current_identity = bool(
            current.get("feedbackKey")
            or current.get("subjectType")
            or current.get("publicationId")
            or current.get("contentId")
        )
        return has_current_identity, (
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

    @staticmethod
    def _first_valid_title(candidates: tuple, is_publication: bool) -> str | None:
        for candidate in candidates:
            title = Speech.humanize_spoken_title(candidate)
            if title and (
                not is_publication
                or ContentUtils.publication_title({"publicationTitle": title})
            ):
                return title
        return None

    @staticmethod
    def _publication_source(current: dict, active: dict, active_matches: bool) -> str:
        publishers = (
            current.get("organizationName"),
            current.get("creatorName"),
            active.get("organizationName") if active_matches else None,
            active.get("creatorName") if active_matches else None,
        )
        publisher = next(
            (
                Speech.humanize_spoken_title(value)
                for value in publishers
                if value and not Speech.is_bad_credit(value)
            ),
            None,
        )
        return f"a publication from {publisher}" if publisher else "a publication"

    @classmethod
    def subject_title(cls, subject: dict | None, store: dict | None = None) -> str:
        current = subject if isinstance(subject, dict) else {}
        saved = store if isinstance(store, dict) else {}
        active = saved.get("activePlayback") or {}
        queue = saved.get("playbackQueue") or {}
        discovery_subject = cls._discovery_subject(current, active, queue)
        if discovery_subject:
            return discovery_subject
        has_current_identity, is_publication = cls._publication_identity(current, active)
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
        title = cls._first_valid_title(candidates, is_publication)
        if title:
            return title
        if is_publication:
            return cls._publication_source(current, active, active_matches)
        return "this recording"

    @staticmethod
    def feedback_question(title: str) -> str:
        return f"Did you enjoy {Speech.escape_ssml_lite(title)}? Say enjoyed, it was okay, not enjoyed, or skip."

    @staticmethod
    def resuming_speech(subject: dict | None, store: dict, *, skipped: bool = False) -> str:
        title = Speech.escape_ssml_lite(AlexaFeedback.subject_title(subject, store))
        prefix = "Ok." if skipped else "Thanks for the feedback."
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
    def discovery_continuation_question(context: dict) -> str:
        subject = DiscoverySpeech.subject(context) or "that content"
        return f"Would you like to continue listening to {Speech.escape_ssml_lite(subject)}?"

    @staticmethod
    def discovery_continuation_reprompt(context: dict) -> str:
        subject = DiscoverySpeech.subject(context) or "that content"
        safe_subject = Speech.escape_ssml_lite(subject)
        return f"Say yes to continue listening to {safe_subject}, or no to choose something else."

    @staticmethod
    def discovery_continuing_speech(context: dict) -> str:
        subject = DiscoverySpeech.subject(context) or "that content"
        return f"Continuing {Speech.escape_ssml_lite(subject)}."

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
        user_name = store.get("userName") or store.get("fullName")
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
