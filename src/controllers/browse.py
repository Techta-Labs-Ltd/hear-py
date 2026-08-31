from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.request import AlexaRequest
from src.models.browse import Browse


class WhatsTrendingHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._model = deps.browse if deps else Browse()

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return AlexaRequest.get_request_type(
            handler_input
        ) == "IntentRequest" and AlexaRequest.get_intent_name(handler_input) in {
            "WhatsTrendingIntent",
            "PlayRecommendationIntent",
        }

    async def handle(self, handler_input: HandlerInput):
        return await self._model.trending(handler_input)


class BrowseContentHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._model = deps.browse if deps else Browse()

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return AlexaRequest.get_request_type(
            handler_input
        ) == "IntentRequest" and AlexaRequest.get_intent_name(handler_input) in {
            "BrowseContentIntent",
            "BrowseByCategoryIntent",
        }

    async def handle(self, handler_input: HandlerInput):
        return await self._model.content(handler_input)


class BrowseNavigationHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._model = deps.browse if deps else Browse()

    def can_handle(self, handler_input: HandlerInput) -> bool:
        if AlexaRequest.get_request_type(handler_input) != "IntentRequest":
            return False
        intent_name = AlexaRequest.get_intent_name(handler_input)
        if intent_name == "ShowMoreBrowseIntent":
            return True
        return intent_name in {
            "AMAZON.NextIntent",
            "AMAZON.PreviousIntent",
            "ShowPreviousBrowseIntent",
        } and self._model.has_active_ambiguity(handler_input)

    async def handle(self, handler_input: HandlerInput):
        if AlexaRequest.get_intent_name(handler_input) in {
            "AMAZON.PreviousIntent",
            "ShowPreviousBrowseIntent",
        }:
            return await self._model.previous(handler_input)
        return await self._model.more(handler_input)
