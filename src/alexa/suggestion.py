from __future__ import annotations

from src.alexa.context import RequestContext
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.suggestion_policy import SuggestionPolicy
from src.services.logging_control import ApplicationLog


class SuggestionConfirmation:
    def __init__(
        self,
        *,
        user,
        browse,
        play_content,
        play_creator,
        play_organization,
        enjoyed_feedback,
        not_enjoyed_feedback,
    ) -> None:
        self._user = user
        self._browse = browse
        self._play_content = play_content
        self._play_creator = play_creator
        self._play_organization = play_organization
        self._enjoyed_feedback = enjoyed_feedback
        self._not_enjoyed_feedback = not_enjoyed_feedback

    @staticmethod
    def _set_intent(handler_input, intent: str, slots: dict) -> None:
        attrs = RequestContext.request(handler_input)
        attrs["_nlp"] = {"intent": intent, "slots": slots}
        RequestContext.replace_request(handler_input, attrs)

    async def confirm(self, handler_input, store: dict):
        decision = SuggestionPolicy.decide(store)
        if decision.kind == "lost":
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml("Sorry, I lost track. What would you like to listen to?")
                )
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        self._user.update(handler_input, {"pendingNlpSuggestion": None})
        ApplicationLog.info("Hear: NLP suggestion confirmed action=%s", decision.action)
        if decision.kind == "feedback" and decision.action:
            handler = {
                "feedback_enjoyed": self._enjoyed_feedback,
                "feedback_not_enjoyed": self._not_enjoyed_feedback,
            }.get(decision.action)
            if handler:
                return await handler.execute(handler_input)
        if decision.kind == "action" and decision.action:
            if decision.intent:
                self._set_intent(handler_input, decision.intent, dict(decision.slots))
            handler = {
                "play_content": self._play_content.execute,
                "play_creator": self._play_creator.execute,
                "play_organization": self._play_organization.execute,
                "browse_trending": self._browse.trending,
                "browse_content": self._browse.content,
                "browse_more": self._browse.more,
            }.get(decision.action)
            if handler:
                return await handler(handler_input)
        return (
            handler_input.response_builder.speak(Ssml.ssml("What would you like to listen to?"))
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )
