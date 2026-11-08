from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.request import AlexaRequest
from src.alexa.ssml import Ssml


class LinkPhoneSpeech:
    CARD_TITLE = "Link your phone"
    FAILED = (
        "Sorry, I couldn't make a code just now. Please try again in a moment."
    )

    @staticmethod
    def code(code: str) -> str:
        digits = f'<say-as interpret-as="digits">{code}</say-as>'
        return (
            f"Your code is {digits}. On your phone, open Hear Service and say link Alexa, "
            f"then say the code. Here it is again: {digits}. It works for ten minutes."
        )

    @staticmethod
    def card(code: str) -> str:
        return (
            f"Your code is {code}. On your phone, open Hear Service and say link Alexa, "
            "then say the code. It works for ten minutes."
        )


class LinkPhoneHandler(AbstractRequestHandler):
    INTENT = "LinkPhoneIntent"

    def __init__(self, bind_client) -> None:
        self._bind_client = bind_client

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == self.INTENT
        )

    async def handle(self, handler_input: HandlerInput):
        result = await self._bind_client(handler_input).create_link_code()
        code = str((result or {}).get("code") or "").strip()
        builder = handler_input.response_builder
        if not code.isdigit():
            return builder.speak(Ssml.ssml(LinkPhoneSpeech.FAILED)).set_should_end_session(True).response
        return (
            builder.speak(Ssml.ssml(LinkPhoneSpeech.code(code)))
            .with_simple_card(LinkPhoneSpeech.CARD_TITLE, LinkPhoneSpeech.card(code))
            .set_should_end_session(True)
            .response
        )
