"""AWS Lambda entry point for the Hear Alexa skill."""
from __future__ import annotations

import asyncio
import logging

from aws_lambda_powertools import Logger, Tracer

from src.application import build_skill
from src.clients.resolver import ResolverUnavailable, client as resolver_client
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


async def _resolver_healthcheck() -> dict:
    """Exercise the resolver from the deployed Lambda runtime without exposing secrets."""
    try:
        result = await resolver_client.resolve("herne bay")
    except ResolverUnavailable as exc:
        logger.error("Resolver healthcheck failed", extra={"reason": str(exc)})
        return {"ok": False, "service": "resolver", "reason": str(exc)}

    locations = result.entities_of_type("location")
    canonical_value = locations[0].canonical_value if locations else None
    healthy = result.status == "resolved" and canonical_value == "Herne Bay"
    return {
        "ok": healthy,
        "service": "resolver",
        "status": result.status,
        "canonicalValue": canonical_value,
    }


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict, context) -> dict:
    try:
        event = event or {}
        if event.get("diagnostic") == "resolver":
            return _run(_resolver_healthcheck())
        if not _is_alexa_event(event):
            request_type = (event.get("request") or {}).get("type")
            logger.info("Non-Alexa event ignored", extra={"requestType": request_type})
            return {"ok": True, "ignored": "non-alexa-event"}
        return _run(_get_skill().invoke(event, context))
    except Exception:
        logger.exception("Lambda handler failed")
        return last_resort_skill_response()
