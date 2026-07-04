from __future__ import annotations
from config import settings
from src.utils.speech import ERROR_GENERIC

import sentry_sdk
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration


def sentry_enabled() -> bool:
    """Return whether Sentry SDK is enabled via SENTRY_DSN."""
    return bool(settings.SENTRY_DSN)


def dsn_configured() -> bool:
    """Return whether a Sentry DSN has been configured."""
    return bool(settings.SENTRY_DSN)


_init_flag = False


def init_sentry() -> None:
    """Initialise Sentry SDK with the configured DSN and environment settings."""
    global _init_flag
    if _init_flag or not settings.SENTRY_DSN:
        return
    try:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.SENTRY_ENVIRONMENT or settings.STAGE or settings.NODE_ENV or "development",
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            integrations=[AwsLambdaIntegration(timeout_warning=True)],
            before_send=_before_send,
        )
        _init_flag = True
    except Exception:
        pass


def _before_send(event: dict, hint: dict) -> dict | None:
    if event.get("request") and isinstance(event["request"], dict):
        data = event["request"].get("data")
        if isinstance(data, str) and len(data) > 8192:
            event["request"]["data"] = data[:8192] + "...[truncated]"
    return event


def capture_skill_exception(handler_input, error: Exception) -> None:
    """Capture an exception in the Alexa skill and report it to Sentry."""
    if not sentry_enabled():
        return
    try:
        with sentry_sdk.push_scope() as scope:
            scope.set_context("alexa", _alexa_context(handler_input))
            sentry_sdk.capture_exception(error)
    except Exception:
        pass


def _alexa_context(handler_input) -> dict:
    envelope = getattr(handler_input, "request_envelope", {}) or {}
    request = envelope.get("request", {})
    return {
        "requestId": request.get("requestId", ""),
        "requestType": request.get("type", ""),
        "sessionId": (envelope.get("session") or {}).get("sessionId", ""),
        "locale": request.get("locale", ""),
    }


async def flush_sentry(max_ms: int = 2000) -> None:
    """Block until all queued Sentry events have been sent or max_ms elapses."""
    if not sentry_enabled():
        return
    try:
        sentry_sdk.flush(timeout=max_ms / 1000.0)
    except Exception:
        pass


def last_resort_skill_response() -> dict:
    """Return a minimal Alexa skill response suitable for error paths."""

    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "SSML", "ssml": f"<speak>{ERROR_GENERIC}</speak>"},
            "shouldEndSession": True,
        },
    }


def wrap_lambda_handler(handler):
    """Return the handler unchanged.

    With sentry-sdk 2.x, ``AwsLambdaIntegration`` (configured in
    :func:`init_sentry`) instruments the Lambda handler automatically, so no
    manual wrapping is required.
    """
    return handler
