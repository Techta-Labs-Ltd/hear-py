from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractExceptionHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech


class ErrorHandler(AbstractExceptionHandler):
    logger = logging.getLogger(__name__)

    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput, exception: Exception) -> bool:
        return True

    async def handle(self, handler_input: HandlerInput, exception: Exception):
        try:
            await self._flush_and_report(handler_input, exception)
            request_type = AlexaRequest.get_request_type(handler_input)
            self.logger.error(
                "Unhandled error: requestType=%s intent=%s message=%s",
                request_type,
                AlexaRequest.get_intent_name(handler_input),
                exception,
            )
            if request_type == "SessionEndedRequest":
                return {}
            if isinstance(request_type, str) and request_type.startswith("AudioPlayer."):
                return {}
            if handler_input and hasattr(handler_input, "response_builder"):
                return (
                    handler_input.response_builder.speak(Speech.ERROR_GENERIC)
                    .reprompt(Speech.ERROR_GENERIC)
                    .set_should_end_session(False)
                    .response
                )
        except Exception as inner:
            self.logger.error("Hear: ErrorHandler failed %s", inner)
        try:
            return AlexaResponse.last_resort_skill_response()
        except Exception:
            return {}

    async def _flush_and_report(self, handler_input: HandlerInput, exception: Exception) -> None:
        try:
            await self._deps.playback.flush_previous(
                AlexaRequest.get_user_id(handler_input), None, handler_input
            )
        except Exception as flush_err:
            self.logger.warning("Hear: ErrorHandler flush failed %s", flush_err)
        try:
            self._deps.error_reporter.capture(handler_input, exception)
            await self._deps.error_reporter.flush(2000)
        except Exception as capture_error:
            self.logger.warning("Hear: captureSkillException failed %s", capture_error)
