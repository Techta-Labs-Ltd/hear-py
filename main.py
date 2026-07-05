import asyncio
import base64
import os

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import APIGatewayRestResolver

from src.runtime import AsyncSkill

from config import settings

from src.services.sentry import init_sentry, wrap_lambda_handler, last_resort_skill_response
from src.adapters.memory_persistence import MemoryPersistenceAdapter
from src.adapters.dynamodb_persistence import build_dynamo_adapter

from src.middleware import register_middleware

from src.handlers.intents import (
    LaunchRequestHandler, WhatsTrendingHandler,
    BrowseContentHandler, PlayByCreatorHandler, PlayByOrganizationHandler,
    PlayContentHandler, ShowMoreBrowseHandler,
    SetPlaybackSpeedHandler, IncreaseSpeedHandler, DecreaseSpeedHandler,
    PauseIntentHandler, ResumeIntentHandler, NextIntentHandler, PreviousIntentHandler,
    RepeatIntentHandler, RewindIntentHandler, FastForwardIntentHandler,
    WhoIsCreatorHandler, FollowCreatorHandler, UnfollowCreatorHandler,
    ReportContentHandler, ReportCreatorHandler, WhatsThisAboutHandler,
    HearNotificationsHandler,
    HelpIntentHandler, CancelIntentHandler, YesIntentHandler, NoIntentHandler,
    NavigateHomeHandler, UnsupportedIntentHandler, SessionEndedHandler,
    FallbackHandler, UnmatchedIntentHandler, UnknownRequestHandler,
)
from src.handlers.audio import (
    PlaybackStartedHandler, PlaybackNearlyFinishedHandler, PlaybackFinishedHandler,
    PlaybackStoppedHandler, PlaybackFailedHandler, PlaybackProgressReportHandler,
)
from src.handlers.feedback import (
    FeedbackEnjoyedHandler, FeedbackSomewhatHandler, FeedbackNotEnjoyedHandler,
    SkipFeedbackHandler,
)
from src.handlers.notifications import EnableNotificationsHandler, DisableNotificationsHandler

from src.webhooks.index import verify_secret
from src.webhooks.settings import handle_settings_webhook
from src.webhooks.notification_webhook import handle_notification_webhook

logger = Logger()
tracer = Tracer()

init_sentry()

ddb_table = (settings.HEAR_DDB_TABLE or "").strip()
_persistence_driver = (settings.HEAR_PERSISTENCE_DRIVER or "dynamodb").lower()


def _resolve_persistence_driver() -> str:
    if _persistence_driver in ("dynamodb", "memory"):
        return _persistence_driver
    if ddb_table:
        return "dynamodb"
    return "memory"


_driver = _resolve_persistence_driver()

if _driver == "dynamodb":
    if not ddb_table:
        logger.warning("Hear: HEAR_DDB_TABLE is unset; falling back to in-memory persistence.")
        _persistence_adapter = MemoryPersistenceAdapter()
    else:
        _persistence_adapter = build_dynamo_adapter(table_name=ddb_table)
else:
    _persistence_adapter = MemoryPersistenceAdapter()

_built_skill = None


def _build_skill():
    builder = AsyncSkill(persistence_adapter=_persistence_adapter)
    # Gate handlers (first), interceptors, and the exception handler — one
    # ordered source of truth lives in src/middleware. Must run before the
    # content handlers registered below so the gates take precedence.
    register_middleware(builder)
    builder.add_request_handler(LaunchRequestHandler())
    builder.add_request_handler(WhatsTrendingHandler())
    builder.add_request_handler(BrowseContentHandler())
    builder.add_request_handler(PlayByCreatorHandler())
    builder.add_request_handler(PlayByOrganizationHandler())
    builder.add_request_handler(PlayContentHandler())
    builder.add_request_handler(ShowMoreBrowseHandler())
    builder.add_request_handler(SetPlaybackSpeedHandler())
    builder.add_request_handler(IncreaseSpeedHandler())
    builder.add_request_handler(DecreaseSpeedHandler())
    builder.add_request_handler(PauseIntentHandler())
    builder.add_request_handler(ResumeIntentHandler())
    builder.add_request_handler(NextIntentHandler())
    builder.add_request_handler(PreviousIntentHandler())
    builder.add_request_handler(RepeatIntentHandler())
    builder.add_request_handler(RewindIntentHandler())
    builder.add_request_handler(FastForwardIntentHandler())
    builder.add_request_handler(WhoIsCreatorHandler())
    builder.add_request_handler(FollowCreatorHandler())
    builder.add_request_handler(UnfollowCreatorHandler())
    builder.add_request_handler(ReportContentHandler())
    builder.add_request_handler(ReportCreatorHandler())
    builder.add_request_handler(WhatsThisAboutHandler())
    builder.add_request_handler(HearNotificationsHandler())
    builder.add_request_handler(PlaybackStartedHandler())
    builder.add_request_handler(PlaybackProgressReportHandler())
    builder.add_request_handler(PlaybackNearlyFinishedHandler())
    builder.add_request_handler(PlaybackFinishedHandler())
    builder.add_request_handler(PlaybackStoppedHandler())
    builder.add_request_handler(PlaybackFailedHandler())
    builder.add_request_handler(FeedbackEnjoyedHandler())
    builder.add_request_handler(FeedbackSomewhatHandler())
    builder.add_request_handler(FeedbackNotEnjoyedHandler())
    builder.add_request_handler(SkipFeedbackHandler())
    builder.add_request_handler(EnableNotificationsHandler())
    builder.add_request_handler(DisableNotificationsHandler())
    builder.add_request_handler(YesIntentHandler())
    builder.add_request_handler(NoIntentHandler())
    builder.add_request_handler(NavigateHomeHandler())
    builder.add_request_handler(UnsupportedIntentHandler())
    builder.add_request_handler(HelpIntentHandler())
    builder.add_request_handler(CancelIntentHandler())
    builder.add_request_handler(SessionEndedHandler())
    builder.add_request_handler(FallbackHandler())
    builder.add_request_handler(UnmatchedIntentHandler())
    builder.add_request_handler(UnknownRequestHandler())
    return builder


async def _webhook_router(event: dict) -> dict:
    try:
        auth = verify_secret(event)
        if auth:
            return auth
        path = event.get("path") or ""
        if path == "/webhook/settings":
            return await handle_settings_webhook(event)
        if path == "/webhook/notification":
            return await handle_notification_webhook(event)
        return {"statusCode": 404, "headers": {"Content-Type": "application/json"}, "body": '{"error":"Not found"}'}
    except Exception as e:
        logger.exception("Webhook router error")
        return {"statusCode": 500, "headers": {"Content-Type": "application/json"}, "body": '{"error":"Internal error"}'}


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict, context) -> dict:
    global _built_skill

    try:
        request_context = event.get("requestContext")
        if request_context and request_context.get("http"):
            path = request_context.get("http", {}).get("path") or event.get("rawPath") or ""
            body = event.get("body") or ""
            if event.get("isBase64Encoded"):
                body = base64.b64decode(body).decode("utf-8")
            normalized = {
                "httpMethod": request_context["http"].get("method"),
                "path": path,
                "headers": event.get("headers") or {},
                "body": body,
            }
            return asyncio.get_event_loop().run_until_complete(_webhook_router(normalized))

        if event.get("httpMethod") == "POST":
            return asyncio.get_event_loop().run_until_complete(_webhook_router(event))

        if not event or not event.get("request") or not (event.get("context") or {}).get("System"):
            logger.info("Non-Alexa event ignored", extra={"requestType": (event.get("request") or {}).get("type")})
            return {"ok": True, "ignored": "non-alexa-event"}

        if _built_skill is None:
            _built_skill = _build_skill()

        return asyncio.get_event_loop().run_until_complete(_built_skill.invoke(event, context))

    except Exception as e:
        logger.exception("Handler error")
        return last_resort_skill_response()
