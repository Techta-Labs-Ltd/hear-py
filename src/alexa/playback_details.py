from __future__ import annotations

from src.alexa.dialog import DialogStateManager
from src.alexa.feedback import AlexaFeedback
from src.alexa.playback_controls import PlaybackControls
from src.alexa.playback_state import PlaybackState
from src.alexa.resume_speech import ResumeSpeech
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.user import User


class PlaybackDetails:
    """Present details for the active, unfinished playback item only."""

    NO_ACTIVE_CONTENT = (
        "There isn't anything playing right now. Play something first, then ask "
        "what it's about or who made it."
    )
    PUBLICATION_ORGANIZATION_UNKNOWN = (
        "I don't have organisation information for this publication."
    )

    def __init__(self, user: User, controls: PlaybackControls) -> None:
        self._user = user
        self._controls = controls
        self._state = PlaybackState(user)

    async def about(self, handler_input):
        return await self._respond(handler_input, kind="about")

    async def creator(self, handler_input):
        return await self._respond(handler_input, kind="creator")

    async def _respond(self, handler_input, *, kind: str):
        store = self._user.snapshot(handler_input)
        if not self._state.has_unfinished(store):
            return (
                handler_input.response_builder.speak(Ssml.ssml(self.NO_ACTIVE_CONTENT))
                .reprompt(Ssml.ssml(self.NO_ACTIVE_CONTENT))
                .set_should_end_session(False)
                .response
            )

        active = self._state.from_store(store) or {}
        speech = self._speech_for(kind, active)
        preserved_prompt = self._preserved_prompt(store, active)
        directive = None
        if preserved_prompt is None:
            directive = await self._controls.pause_active(handler_input)
            store = self._user.snapshot(handler_input)
            active = self._state.from_store(store) or active
            DialogStateManager.activate(handler_input, "resume", context=active)
            store = self._user.snapshot(handler_input)
            prompt = ResumeSpeech.prompt(active, store)
            reprompt = ResumeSpeech.reprompt(active, store)
        else:
            prompt, reprompt = preserved_prompt

        builder = (
            handler_input.response_builder.speak(Ssml.ssml(f"{speech} {prompt}"))
            .reprompt(Ssml.ssml(reprompt))
            .set_should_end_session(False)
        )
        if directive:
            builder = builder.add_directive(directive)
        return builder.response

    @classmethod
    def _speech_for(cls, kind: str, active: dict) -> str:
        title = active.get("title")
        creator = active.get("creatorName")
        if kind == "creator":
            if creator and not Speech.is_bad_credit(creator):
                return Speech.CREATOR_CREDIT(title, Speech.escape_ssml_lite(creator))
            return Speech.CREATOR_CREDIT_UNKNOWN

        if cls._is_publication(active):
            organization = active.get("organizationName")
            if organization and not Speech.is_bad_credit(organization):
                return f"This content is from {Speech.escape_ssml_lite(organization)}."
            return cls.PUBLICATION_ORGANIZATION_UNKNOWN
        return Speech.CONTENT_ABOUT_PHRASE(
            title,
            active.get("summary"),
            None,
            creator,
        )

    @staticmethod
    def _is_publication(active: dict) -> bool:
        return bool(
            active.get("publicationId")
            or active.get("isPublication")
            or active.get("subjectType") == "publication"
        )

    @staticmethod
    def _preserved_prompt(store: dict, active: dict) -> tuple[str, str] | None:
        dialog = DialogStateManager.active_from_store(store) or {}
        context = dialog.get("context") or {}
        dialog_type = dialog.get("type")
        if dialog_type == "feedback":
            prompt = AlexaFeedback.feedback_question(
                AlexaFeedback.subject_title(context, store)
            )
            return prompt, prompt
        if dialog_type == "feedback_continuation":
            return (
                AlexaFeedback.discovery_continuation_question(context),
                AlexaFeedback.discovery_continuation_reprompt(context),
            )
        if dialog_type == "resume":
            subject = context or active
            return ResumeSpeech.prompt(subject, store), ResumeSpeech.reprompt(subject, store)
        if store.get("awaitingContinueAfterFlag"):
            return (
                AlexaFeedback.keep_listening_question(active, store),
                AlexaFeedback.keep_listening_reprompt(active, store),
            )
        return None
