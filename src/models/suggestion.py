from __future__ import annotations

import logging

from src.alexa.context import RequestContext
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.feedback_response import EnjoyedFeedback, NotEnjoyedFeedback
from src.models.play import PlayContent, PlayCreator, PlayOrganization


class SuggestionConfirmation:
    logger = logging.getLogger(__name__)

    def __init__(self, *, deps: object) -> None:
        self._deps = deps

    @staticmethod
    def _set_intent(handler_input, intent: str, slots: dict) -> None:
        attrs = RequestContext.request(handler_input)
        attrs["_nlp"] = {"intent": intent, "slots": slots}
        RequestContext.replace_request(handler_input, attrs)

    async def _creator(self, handler_input, query: str):
        SuggestionConfirmation._set_intent(handler_input, "creator", {"creatorQuery": query})
        return await PlayCreator(deps=self._deps).execute(handler_input)

    async def _organization(self, handler_input, query: str):
        SuggestionConfirmation._set_intent(
            handler_input, "organization", {"organizationQuery": query}
        )
        return await PlayOrganization(deps=self._deps).execute(handler_input)

    async def _category(self, handler_input, query: str):
        SuggestionConfirmation._set_intent(handler_input, "category", {"category": query})
        return await PlayContent(deps=self._deps).execute(handler_input)

    async def _general(self, handler_input, query: str):
        SuggestionConfirmation._set_intent(handler_input, "general", {"topic": query})
        return await PlayContent(deps=self._deps).execute(handler_input)

    async def _local(self, handler_input, query: str):
        del query
        SuggestionConfirmation._set_intent(handler_input, "local", {})
        return await PlayContent(deps=self._deps).execute(handler_input)

    async def _publication(self, handler_input, query: str):
        SuggestionConfirmation._set_intent(
            handler_input,
            "publication",
            {
                "isPublication": True,
                "residualQuery": query,
                "searchPlan": {
                    "query": query,
                    "filter": {"isPublication": True},
                    "sort": "trending",
                },
            },
        )
        return await PlayContent(deps=self._deps).execute(handler_input)

    async def _following(self, handler_input, query: str):
        del query
        SuggestionConfirmation._set_intent(handler_input, "following", {})
        return await PlayContent(deps=self._deps).execute(handler_input)

    async def _trending(self, handler_input, query: str):
        del query
        return await self._deps.browse.trending(handler_input)

    async def _browse(self, handler_input, query: str):
        del query
        return await self._deps.browse.content(handler_input)

    async def _show_more(self, handler_input, query: str):
        del query
        return await self._deps.browse.more(handler_input)

    async def _feedback(self, handler_input, intent: str):
        store = self._deps.user.snapshot(handler_input)
        if not store.get("awaitingFeedback"):
            return None
        if intent == "feedback_enjoyed":
            return await EnjoyedFeedback(deps=self._deps).execute(handler_input)
        if intent == "feedback_not_enjoyed":
            return await NotEnjoyedFeedback(deps=self._deps).execute(handler_input)
        return None

    async def confirm(self, handler_input, store: dict):
        suggestions = store.get("pendingNlpSuggestion") or []
        top = suggestions[0] if suggestions else None
        if not top:
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml("Sorry, I lost track. What would you like to listen to?")
                )
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        self._deps.user.update(handler_input, {"pendingNlpSuggestion": None})
        intent = str(top.get("intent") or "")
        query = str(top.get("query") or "")
        self.logger.info("Hear: NLP suggestion confirmed intent=%s query=%s", intent, query)
        handlers = {
            "creator": self._creator,
            "organization": self._organization,
            "category": self._category,
            "trending": self._trending,
            "local": self._local,
            "publication": self._publication,
            "following": self._following,
            "browse": self._browse,
            "show_more": self._show_more,
            "general": self._general,
        }
        handler = handlers.get(intent)
        if handler:
            return await handler(handler_input, query)
        feedback = await self._feedback(handler_input, intent)
        if feedback:
            return feedback
        return (
            handler_input.response_builder.speak(Ssml.ssml("What would you like to listen to?"))
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )
