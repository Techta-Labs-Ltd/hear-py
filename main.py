"""AWS Lambda entry point for the Hear Alexa skill."""
from __future__ import annotations

import asyncio
import logging

from aws_lambda_powertools import Logger, Tracer

from src.application import build_skill
from src.services.observability import init_sentry, last_resort_skill_response

logger = Logger()
tracer = Tracer()
logging.getLogger().setLevel(logging.INFO)
init_sentry()

_skill = None


def _run(coroutine):
    return asyncio.run(coroutine)


def _build_skill():
    """Compatibility wrapper retained for local tools and older tests."""
    return build_skill()


def _get_skill():
    global _skill
    if _skill is None:
        _skill = build_skill()
    return _skill


def _is_alexa_event(event: dict) -> bool:
    return bool(event and event.get("request") and (event.get("context") or {}).get("System"))


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict, context) -> dict:
    try:
        event = event or {}
        if not _is_alexa_event(event):
            request_type = (event.get("request") or {}).get("type")
            logger.info("Non-Alexa event ignored", extra={"requestType": request_type})
            return {"ok": True, "ignored": "non-alexa-event"}
        return _run(_get_skill().invoke(event, context))
    except Exception:
        logger.exception("Lambda handler failed")
        return last_resort_skill_response()
