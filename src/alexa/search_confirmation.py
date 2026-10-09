from __future__ import annotations

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from src.alexa.dialog import DialogStateManager
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.user import User
from src.services.logging_control import ApplicationLog


class SearchConfirmationPrompt:
    @staticmethod
    def present(handler_input: HandlerInput, user: User, pending: dict) -> Response:
        choice = pending.get("publicationChoice")
        if isinstance(choice, dict) and isinstance(choice.get("pending"), dict):
            topic = {key: value for key, value in pending.items() if key != "publicationChoice"}
            response = SearchConfirmationPrompt._ask(
                handler_input, user, choice["pending"], choice={"name": choice["name"]}
            )
            user.update(handler_input, {"pendingPublicationTopic": topic})
            return response
        return SearchConfirmationPrompt._ask(handler_input, user, pending)

    @staticmethod
    def publication_choice(resolution: dict | None) -> dict | None:
        choice = (resolution or {}).get("publicationChoice")
        return choice if isinstance(choice, dict) and choice.get("name") else None

    @staticmethod
    def declined_publication_topic(handler_input: HandlerInput, user: User) -> dict | None:
        store = user.snapshot(handler_input)
        if not SearchConfirmationPrompt.publication_choice(store.get("pendingResolution")):
            return None
        topic = store.get("pendingPublicationTopic")
        return topic if isinstance(topic, dict) and topic.get("resolution") else None

    @staticmethod
    def _ask(
        handler_input: HandlerInput, user: User, pending: dict, *, choice: dict | None = None
    ) -> Response:
        confirm_text = pending.get("confirmText")
        resolution = dict(pending.get("resolution") or {})
        if choice:
            resolution["publicationChoice"] = choice
        user.update(
            handler_input,
            {
                "awaitingSearchConfirmation": True,
                "pendingResolution": resolution,
                "pendingPublicationTopic": None,
                "awaitingCommunityPlayback": False,
                "_requiresReliableSave": True,
            },
        )
        DialogStateManager.activate(
            handler_input,
            "search_confirmation",
            context={**resolution, "confirmationLabel": confirm_text},
        )
        ApplicationLog.info(
            "Hear: search confirmation asked intent=%s publicationChoice=%s",
            pending.get("intent"),
            bool(choice),
        )
        if choice:
            prompt = Speech.PUBLICATION_CHOICE(choice["name"])
            reprompt = Speech.PUBLICATION_CHOICE_RETRY(choice["name"])
        else:
            escaped = Speech.escape_ssml_lite(
                str(pending.get("ambiguityCandidateName") or confirm_text)
            )
            question = (
                f"Did you mean {escaped}?"
                if pending.get("ambiguityResolution")
                else f"Did you want me to play {escaped}?"
            )
            prompt = reprompt = f"{question} Please say yes or no."
        return (
            handler_input.response_builder.speak(Ssml.ssml(prompt))
            .reprompt(Ssml.ssml(reprompt))
            .set_should_end_session(False)
            .response
        )
