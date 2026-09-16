from __future__ import annotations

import asyncio
import threading

from aws_lambda_powertools import Tracer



from config import settings
from src.alexa.response import AlexaResponse
from src.alexa.runtime import AlexaMetrics
from src.application import Application
from src.clients.events import SqsEventClient, WebhookEventClient
from src.clients.notifications import NotificationApiClient
from src.clients.proactive import ProactiveEventsClient
from src.container import ApplicationContainer
from src.database.dynamodb import DynamoTable
from src.models.resolver import ResolverUnavailable
from src.services.logging_control import ApplicationLog
from src.services.observability import ErrorReporter
from src.services.notification_delivery import NotificationDeliveryService
from src.services.events import OutboundEventService
from src.services.outbox import OutboxRelayService
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
            self._skill = Application.build_skill(container=self.dependencies())
        return self._skill

    @staticmethod
    def is_alexa_event(event: dict) -> bool:
        return bool(event and event.get("request") and (event.get("context") or {}).get("System"))

    async def resolver_healthcheck(self, *, container: ApplicationContainer | None = None) -> dict:
        try:
            result = await (container or self.dependencies()).resolver.resolve("herne bay")
        except ResolverUnavailable as exc:
            ApplicationLog.error("Resolver healthcheck failed error=%s", type(exc).__name__)
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
                ApplicationLog.info("Non-Alexa event ignored requestType=%s", request_type)
                return {"ok": True, "ignored": "non-alexa-event"}
            return self._runtime.run(self.skill().invoke(event, context))
        except Exception:
            ApplicationLog.exception("Lambda handler failed")
            if isinstance(event, dict) and event.get("diagnostic") == "resolver":
                return {"ok": False, "service": "resolver", "reason": "diagnostic failed"}
            request = event.get("request") if isinstance(event, dict) else None
            request_type = request.get("type", "") if isinstance(request, dict) else ""
            return AlexaResponse.last_resort_skill_response(request_type)


class OutboundLambdaApplication:
    tracer = Tracer(service="hear-outbound-events")

    def __init__(self) -> None:
        ApplicationLog.configure(settings.HEAR_LOGGING_ENABLED)
        self._runtime = LambdaRuntime()
        self._events: OutboundEventService | None = None

    def events(self) -> OutboundEventService:
        if self._events is None:
            self._events = OutboundEventService(webhook=WebhookEventClient())
        return self._events

    def handle(self, event: dict, context) -> dict:
        records = (event or {}).get("Records") or []
        message_ids = SqsBatch.message_ids(records)
        deadline = RequestDeadline.from_context(context)
        try:
            return self._runtime.run(self.events().consume(records, deadline=deadline))
        except Exception:
            ApplicationLog.exception("Outbound event batch failed")
            return {
                "batchItemFailures": [{"itemIdentifier": message_id} for message_id in message_ids]
            }


class NotificationLambdaApplication:
    tracer = Tracer(service="hear-proactive-notifications")

    def __init__(self) -> None:
        ApplicationLog.configure(settings.HEAR_LOGGING_ENABLED)
        self._runtime = LambdaRuntime()
        self._delivery: NotificationDeliveryService | None = None

    def delivery(self) -> NotificationDeliveryService:
        if self._delivery is None:
            self._delivery = NotificationDeliveryService(
                NotificationApiClient(),
                ProactiveEventsClient(
                    client_id=settings.ALEXA_PROACTIVE_CLIENT_ID,
                    client_secret=settings.ALEXA_PROACTIVE_CLIENT_SECRET,
                    stage=settings.STAGE,
                ),
            )
        return self._delivery

    def handle(self, event: dict, context) -> dict:
        records = (event or {}).get("Records") or []
        message_ids = SqsBatch.message_ids(records)
        deadline = RequestDeadline.from_context(context)
        try:
            return self._runtime.run(
                self.delivery().consume(records, deadline=deadline)
            )
        except Exception:
            ApplicationLog.exception("Proactive notification batch failed")
            return {
                "batchItemFailures": [{"itemIdentifier": message_id} for message_id in message_ids]
            }


class OutboxRelayLambdaApplication:
    tracer = Tracer(service="hear-outbox-relay")

    def __init__(self) -> None:
        ApplicationLog.configure(settings.HEAR_LOGGING_ENABLED)
        self._runtime = LambdaRuntime()
        self._service: OutboxRelayService | None = None

    def service(self) -> OutboxRelayService:
        if self._service is None:
            table = DynamoTable(
                settings.dynamo_table,
                partition_key=settings.HEAR_DDB_PARTITION_KEY,
                sort_key=settings.HEAR_DDB_SORT_KEY,
                region=settings.ddb_region,
            )
            self._service = OutboxRelayService(table, SqsEventClient())
        return self._service

    def handle(self, event: dict, _context) -> dict:
        records = (event or {}).get("Records") or []
        try:
            return self._runtime.run(self.service().relay(records))
        except Exception:
            ApplicationLog.exception("Outbox relay batch failed")
            identifiers = [
                record.get("eventID") or record.get("eventId")
                for record in records
                if isinstance(record, dict) and (record.get("eventID") or record.get("eventId"))
            ]
            return {"batchItemFailures": [{"itemIdentifier": value} for value in identifiers]}

    def recover(self) -> dict:
        delivered = self._runtime.run(
            self.service().recover_pending(limit=settings.HEAR_OUTBOX_RECOVERY_LIMIT)
        )
        return {"ok": True, "delivered": delivered}


_application = LambdaApplication()
_outbound_application = OutboundLambdaApplication()
_notification_application = NotificationLambdaApplication()
_outbox_relay_application = OutboxRelayLambdaApplication()


@_application.tracer.capture_lambda_handler
@AlexaMetrics.provider.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context) -> dict:
    return _application.handle(event, context)


@_outbound_application.tracer.capture_lambda_handler
def outbound_handler(event: dict, context) -> dict:
    return _outbound_application.handle(event, context)


@_notification_application.tracer.capture_lambda_handler
def notification_handler(event: dict, context) -> dict:
    return _notification_application.handle(event, context)


@_outbox_relay_application.tracer.capture_lambda_handler
def outbox_relay_handler(event: dict, context) -> dict:
    return _outbox_relay_application.handle(event, context)


@_outbox_relay_application.tracer.capture_lambda_handler
def outbox_recovery_handler(event: dict, context) -> dict:
    return _outbox_relay_application.recover()
