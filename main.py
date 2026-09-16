from __future__ import annotations

import asyncio
import threading

from aws_lambda_powertools import Logger, Tracer

from config import settings
from src.alexa.response import AlexaResponse
from src.alexa.runtime import AlexaMetrics
from src.application import Application
from src.container import ApplicationContainer
from src.models.resolver import ResolverUnavailable
from src.services.logging_control import ApplicationLog
from src.services.observability import ErrorReporter
from src.utils.deadline import RequestDeadline
from src.utils.events import SqsBatch


class LambdaRuntime:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._lock = threading.Lock()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def run(self, coroutine):
        with self._lock:
            if self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
            return self._loop.run_until_complete(coroutine)


class LambdaApplication:
    logger = Logger()
    tracer = Tracer()

    def __init__(self) -> None:
        ApplicationLog.configure(settings.HEAR_LOGGING_ENABLED)
        self._error_reporter = ErrorReporter()
        self._error_reporter.initialize()
        self._runtime = LambdaRuntime()
        self._dependencies: ApplicationContainer | None = None
        self._skill = None

    @property
    def runtime(self) -> LambdaRuntime:
        return self._runtime

    def dependencies(self) -> ApplicationContainer:
        if self._dependencies is None:
            self._dependencies = ApplicationContainer(error_reporter=self._error_reporter)
        return self._dependencies

    def skill(self):
        if self._skill is None:
            self._skill = Application.build_skill(deps=self.dependencies())
        return self._skill

    @staticmethod
    def is_alexa_event(event: dict) -> bool:
        return bool(event and event.get("request") and (event.get("context") or {}).get("System"))

    async def resolver_healthcheck(self, *, deps=None) -> dict:
        try:
            result = await (deps or self.dependencies()).resolver.resolve("herne bay")
        except ResolverUnavailable as exc:
            self.logger.error("Resolver healthcheck failed", extra={"reason": str(exc)})
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

    def handle(self, event: dict, context) -> dict:
        try:
            event = event or {}
            if event.get("diagnostic") == "resolver":
                return self._runtime.run(self.resolver_healthcheck())
            if not self.is_alexa_event(event):
                request_type = (event.get("request") or {}).get("type")
                self.logger.info("Non-Alexa event ignored", extra={"requestType": request_type})
                return {"ok": True, "ignored": "non-alexa-event"}
            return self._runtime.run(self.skill().invoke(event, context))
        except Exception:
            self.logger.exception("Lambda handler failed")
            if isinstance(event, dict) and event.get("diagnostic") == "resolver":
                return {"ok": False, "service": "resolver", "reason": "diagnostic failed"}
            request = event.get("request") if isinstance(event, dict) else None
            request_type = request.get("type", "") if isinstance(request, dict) else ""
            return AlexaResponse.last_resort_skill_response(request_type)


class OutboundLambdaApplication:
    logger = Logger(service="hear-outbound-events")
    tracer = Tracer(service="hear-outbound-events")

    def __init__(self) -> None:
        ApplicationLog.configure(settings.HEAR_LOGGING_ENABLED)
        self._runtime = LambdaRuntime()
        self._dependencies: ApplicationContainer | None = None

    def dependencies(self) -> ApplicationContainer:
        if self._dependencies is None:
            self._dependencies = ApplicationContainer()
        return self._dependencies

    def handle(self, event: dict, context) -> dict:
        records = (event or {}).get("Records") or []
        message_ids = SqsBatch.message_ids(records)
        deadline = RequestDeadline.from_context(context)
        try:
            return self._runtime.run(self.dependencies().events.consume(records, deadline=deadline))
        except Exception:
            self.logger.exception("Outbound event batch failed")
            return {
                "batchItemFailures": [{"itemIdentifier": message_id} for message_id in message_ids]
            }


class NotificationLambdaApplication:
    logger = Logger(service="hear-proactive-notifications")
    tracer = Tracer(service="hear-proactive-notifications")

    def __init__(self) -> None:
        ApplicationLog.configure(settings.HEAR_LOGGING_ENABLED)
        self._runtime = LambdaRuntime()
        self._dependencies: ApplicationContainer | None = None

    def dependencies(self) -> ApplicationContainer:
        if self._dependencies is None:
            self._dependencies = ApplicationContainer()
        return self._dependencies

    def handle(self, event: dict, context) -> dict:
        records = (event or {}).get("Records") or []
        message_ids = SqsBatch.message_ids(records)
        deadline = RequestDeadline.from_context(context)
        try:
            return self._runtime.run(
                self.dependencies().notification_delivery.consume(records, deadline=deadline)
            )
        except Exception:
            self.logger.exception("Proactive notification batch failed")
            return {
                "batchItemFailures": [{"itemIdentifier": message_id} for message_id in message_ids]
            }


_application = LambdaApplication()
_outbound_application = OutboundLambdaApplication()
_notification_application = NotificationLambdaApplication()


@_application.logger.inject_lambda_context
@_application.tracer.capture_lambda_handler
@AlexaMetrics.provider.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context) -> dict:
    return _application.handle(event, context)


@_outbound_application.logger.inject_lambda_context
@_outbound_application.tracer.capture_lambda_handler
def outbound_handler(event: dict, context) -> dict:
    return _outbound_application.handle(event, context)


@_notification_application.logger.inject_lambda_context
@_notification_application.tracer.capture_lambda_handler
def notification_handler(event: dict, context) -> dict:
    return _notification_application.handle(event, context)
