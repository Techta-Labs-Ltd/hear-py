from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractExceptionHandler
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.services.logging_control import ApplicationLog
from src.services.observability import ErrorReporter


class ErrorHandler(AbstractExceptionHandler):

    def __init__(self, error_reporter: ErrorReporter) -> None:
        self._error_reporter = error_reporter

    def can_handle(self, handler_input: HandlerInput, exception: Exception) -> bool:
        return True

    async def handle(self, handler_input: HandlerInput, exception: Exception):
        try:
            await self._flush_and_report(handler_input, exception)
            request_type = AlexaRequest.get_request_type(handler_input)
            ApplicationLog.error(
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
            ApplicationLog.error("Hear: ErrorHandler failed %s", inner)
        try:
            return AlexaResponse.last_resort_skill_response(
                AlexaRequest.get_request_type(handler_input)
            )
        except Exception:
            return {}

    async def _flush_and_report(self, handler_input: HandlerInput, exception: Exception) -> None:
        try:
            self._error_reporter.capture(handler_input, exception)
            await self._error_reporter.flush(2000)
        except Exception as capture_error:
            ApplicationLog.warning("Hear: captureSkillException failed %s", capture_error)
