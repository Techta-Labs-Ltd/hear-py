from __future__ import annotations

import sentry_sdk
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration

from config import settings
from src.utils.speech import ERROR_GENERIC


class ErrorReporter:
    def __init__(self) -> None:
        self._initialized = False

    @property
    def enabled(self) -> bool:
        return bool(settings.SENTRY_DSN)

    def initialize(self) -> None:
        if self._initialized or not self.enabled:
            return
        try:
            sentry_sdk.init(
                dsn=settings.SENTRY_DSN,
                environment=(
                    settings.SENTRY_ENVIRONMENT
                    or settings.STAGE
                    or settings.NODE_ENV
                    or "development"
                ),
                traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
                integrations=[AwsLambdaIntegration(timeout_warning=True)],
                before_send=self._before_send,
            )
            self._initialized = True
        except Exception:
            return

    def _before_send(self, event: dict, hint: dict) -> dict | None:
        request = event.get("request")
        if request and isinstance(request, dict):
            data = request.get("data")
            if isinstance(data, str) and len(data) > 8192:
                request["data"] = f"{data[:8192]}...[truncated]"
        return event

    def capture(self, handler_input, error: Exception) -> None:
        if not self.enabled:
            return
        try:
            with sentry_sdk.push_scope() as scope:
                scope.set_context("alexa", self._alexa_context(handler_input))
                sentry_sdk.capture_exception(error)
        except Exception:
            return

    def _alexa_context(self, handler_input) -> dict:
        envelope = getattr(handler_input, "request_envelope", {}) or {}
        request = envelope.get("request", {})
        return {
            "requestId": request.get("requestId", ""),
            "requestType": request.get("type", ""),
            "sessionId": (envelope.get("session") or {}).get("sessionId", ""),
            "locale": request.get("locale", ""),
        }

    async def flush(self, max_ms: int = 2000) -> None:
        if not self.enabled:
            return
        try:
            sentry_sdk.flush(timeout=max_ms / 1000.0)
        except Exception:
            return


error_reporter = ErrorReporter()


def sentry_enabled() -> bool:
    return error_reporter.enabled


def init_sentry() -> None:
    error_reporter.initialize()


def capture_skill_exception(handler_input, error: Exception) -> None:
    error_reporter.capture(handler_input, error)


async def flush_sentry(max_ms: int = 2000) -> None:
    await error_reporter.flush(max_ms)


def last_resort_skill_response() -> dict:
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {
                "type": "SSML",
                "ssml": f"<speak>{ERROR_GENERIC}</speak>",
            },
            "shouldEndSession": True,
        },
    }
