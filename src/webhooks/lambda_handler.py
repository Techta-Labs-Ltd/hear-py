from __future__ import annotations

import asyncio
import logging

from aws_lambda_powertools import Logger, Tracer

from src.services.observability import init_sentry
from src.webhooks.router import normalize_http_event, route_webhook

logger = Logger()
tracer = Tracer()
logging.getLogger().setLevel(logging.INFO)
init_sentry()


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict, context) -> dict:
    """Normalize and route one API Gateway webhook event."""
    return asyncio.run(route_webhook(normalize_http_event(event or {})))
