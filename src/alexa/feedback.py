from __future__ import annotations

import re

from src.alexa.discovery_speech import DiscoverySpeech
from src.alexa.entities import AlexaEntities
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.utils.content import ContentUtils


class AlexaFeedback:
    _NEGATIONS = frozenset(
        {"not", "didn't", "didnt", "don't", "dont", "wasn't", "wasnt", "never", "no", "nope"}
    )
    _DISLIKE_WORDS = frozenset(
        {"bad", "poor", "boring", "awful", "terrible", "rubbish", "hated", "hate", "dislike", "disliked"}
    )
    _LIKE_STEMS = (
        "enjoy",
        "joy",
        "like",
        "love",
        "good",
        "great",
        "brilliant",
        "excellent",
        "fantastic",
        "lovely",
        "amazing",
        "wonderful",
    )
    _DYNAMIC_FEEDBACK_IDS = {
        "enjoyed": "enjoyed",
        "somewhat": "somewhat",
        "not-enjoyed": "not enjoyed",
    }

    @staticmethod
    def normalize_slot(slot) -> str | None:
        """Use one resolved feedback entity before interpreting Alexa's spoken text."""
        resolved = {
            AlexaFeedback._DYNAMIC_FEEDBACK_IDS[entity_id]
            for entity_id in AlexaRequest.get_resolved_slot_ids(slot)
            if entity_id in AlexaFeedback._DYNAMIC_FEEDBACK_IDS
        }
        if len(resolved) == 1:
            return resolved.pop()
        if resolved:
            return None
        return AlexaFeedback.normalize_value(AlexaRequest.get_spoken_slot_value(slot))

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
        if text in {"ok", "so so", "so-so"} or any(
            phrase in text
            for phrase in (
                "somewhat",
                "okay",
                "was ok",
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
        words = re.findall(r"[a-z']+", text)
        negated = any(word in AlexaFeedback._NEGATIONS for word in words)
        if text in {"not really", "not at all"} or any(
            word in AlexaFeedback._DISLIKE_WORDS for word in words
        ):
            return "not enjoyed"
        if any(word.startswith(AlexaFeedback._LIKE_STEMS) for word in words) or text in {
            "five stars",
            "thumbs up",
        }:
            return "not enjoyed" if negated else "enjoyed"
        if text in {"yes", "yes i did", "yeah", "yep", "i did"}:
            return "enjoyed"
        if text in {"no", "nope", "no i didn't", "i didn't"}:
            return "not enjoyed"
        return None

    @staticmethod
    def _discovery_subject(current: dict, active: dict, queue: dict) -> str | None:
        discovery_context = (
            current.get("discoveryContext")
            or active.get("discoveryContext")
            or queue.get("discoveryContext")
        )
        if not isinstance(discovery_context, dict):
            return None
        if str(discovery_context.get("kind") or "").strip().casefold() in {
            "trending",
            "recommendation",
        }:
            return None
        return (
            ContentUtils.publication_title({"discoveryContext": discovery_context})
            if discovery_context.get("kind") == "publication"
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
        has_current_identity, is_publication = cls._publication_identity(current, active)
        active_matches = not has_current_identity or (
            str(active.get("publicationId") or active.get("contentId") or "")
            == str(current.get("publicationId") or current.get("contentId") or "")
        )
        queue_matches = not current.get("publicationId") or (
            str(queue.get("publicationId") or "")
            == str(current.get("publicationId") or "")
        )
        if is_publication:
            publication = cls._first_valid_title(
                (
                    current.get("publicationTitle"),
                    current.get("subjectTitle"),
                    active.get("publicationTitle") if active_matches else None,
                    active.get("subjectTitle") if active_matches else None,
                    queue.get("publicationTitle") if queue_matches else None,
                    current.get("title"),
                ),
                True,
            )
            return publication or cls._publication_source(current, active, active_matches)

        source = cls._first_valid_title(
            (
                current.get("organizationName"),
                active.get("organizationName") if active_matches else None,
                current.get("creatorName"),
                active.get("creatorName") if active_matches else None,
                queue.get("organizationName"),
                queue.get("creatorName"),
            ),
            False,
        )
        if source and not Speech.is_bad_credit(source):
            return source

        discovery_subject = cls._discovery_subject(current, active, queue)
        if discovery_subject:
            return discovery_subject
        discovery_context = (
            current.get("discoveryContext")
            or active.get("discoveryContext")
            or queue.get("discoveryContext")
        )
        if isinstance(discovery_context, dict):
            kind = str(discovery_context.get("kind") or "").strip().casefold()
            if kind == "trending":
                return "what's trending"
            if kind == "recommendation":
                return "your recommendations"
        return "this recording"

    @classmethod
    def feedback_subject(cls, subject: dict | None, store: dict | None = None) -> str:
        title = cls.subject_title(subject, store)
        current = subject if isinstance(subject, dict) else {}
        saved = store if isinstance(store, dict) else {}
        active = saved.get("activePlayback") or {}
        queue = saved.get("playbackQueue") or {}
        _, is_publication = cls._publication_identity(current, active)
        if not is_publication:
            return title
        publisher = next(
            (
                str(value).strip()
                for value in (
                    current.get("organizationName"),
                    active.get("organizationName"),
                    queue.get("organizationName"),
                    current.get("creatorName"),
                    active.get("creatorName"),
                    queue.get("creatorName"),
                )
                if value and str(value).strip() and not Speech.is_bad_credit(value)
            ),
            None,
        )
        if publisher and publisher.casefold() not in title.casefold():
            return f"{title} from {publisher}"
        return title

    @staticmethod
    def feedback_question(title: str) -> str:
        return f"Did you enjoy {Speech.escape_ssml_lite(title)}? {Speech.FEEDBACK_OPTIONS}"

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
            AlexaFeedback.feedback_subject(pending, store)
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(prompt))
            .reprompt(Ssml.ssml(prompt))
            .add_directive(stop_directive)
            .add_directive(AlexaEntities.build_feedback_dynamic_entities_directive())
            .with_should_end_session(False)
            .get_response()
        )

    @staticmethod
    def present_pending_feedback(handler_input, store: dict):
        pending = store.get("pendingFeedback") or {}
        title = AlexaFeedback.feedback_subject(pending, store)
        creator_name = (
            pending.get("organizationName")
            or pending.get("creatorName")
            or store.get("feedbackCreator")
        )
        creator = Speech.escape_ssml_lite(creator_name) if creator_name else "the creator"
        user_name = store.get("userName") or store.get("fullName")
        if pending.get("subjectType") == "publication":
            speech = AlexaFeedback.feedback_question(title)
        else:
            speech = Speech.LAUNCH_PENDING_FEEDBACK(title, creator, user_name)
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Ssml.ssml(AlexaFeedback.feedback_question(title)))
            .add_directive(AlexaEntities.build_feedback_dynamic_entities_directive())
            .with_should_end_session(False)
            .get_response()
        )
