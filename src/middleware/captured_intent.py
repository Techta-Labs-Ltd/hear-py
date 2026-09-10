from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor

from src.alexa.captured_intent import CapturedIntentRouter


class CapturedIntentInterceptor(AbstractRequestInterceptor):
    def process(self, handler_input) -> None:
        CapturedIntentRouter.apply(handler_input)
