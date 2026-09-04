from __future__ import annotations

import inspect

from config import settings
from src.clients.alexa import AlexaClient
from src.clients.alexa_settings import AlexaSettingsClient
from src.clients.events import SqsEventClient, WebhookEventClient
from src.clients.hear import HearApiClient
from src.clients.proactive import ProactiveEventsClient
from src.clients.progressive import ProgressiveResponseClient
from src.clients.resolver import ResolverClient, ResolverOptions
from src.database.notification_inbox import NotificationInboxFactory
from src.models.availability import Availability
from src.models.browse import Browse
from src.models.feedback import FeedbackService
from src.models.listener import Listener
from src.models.notifications import Notification
from src.models.onboarding import Onboarding
from src.models.permission import Permission
from src.models.playback import Playback
from src.models.playback_state import PlaybackQueue, PlaybackState
from src.models.report import Report
from src.models.search import Search
from src.models.user import User
from src.services.alexa_locality import AlexaLocalityService
from src.services.alexa_profile import ListenerProfileService
from src.services.alexa_reminder import AlexaReminderService
from src.services.events import OutboundEventService
from src.services.listener_identity import ListenerIdentityService
from src.services.listener_sync import ListenerSyncService
from src.services.notification_delivery import NotificationDeliveryService
from src.services.observability import ErrorReporter


class ApplicationContainer:
    COMPONENT_NAMES = frozenset(
        {
            "locality",
            "listener_profile",
            "listener_sync",
            "listener_identity",
            "events",
            "feedback",
            "browse",
            "availability",
            "playback",
            "reminders",
            "user",
            "listeners",
            "onboarding",
            "reports",
            "playback_store",
            "playback_queue",
            "alexa_settings",
            "alexa",
            "heara",
            "resolver",
            "progressive",
            "permission",
            "notification_inbox",
            "proactive_events",
            "notification_delivery",
            "notifications",
            "error_reporter",
        }
    )
    __slots__ = (
        "locality",
        "listener_profile",
        "listener_sync",
        "listener_identity",
        "events",
        "feedback",
        "browse",
        "availability",
        "playback",
        "search",
        "reminders",
        "user",
        "listeners",
        "onboarding",
        "reports",
        "alexa",
        "heara",
        "resolver",
        "progressive",
        "error_reporter",
        "permission",
        "notification_inbox",
        "proactive_events",
        "notification_delivery",
        "notifications",
    )

    def __init__(self, **components) -> None:
        unknown = set(components).difference(self.COMPONENT_NAMES)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise TypeError(f"Unknown application components: {names}")
        settings_client = components.get("alexa_settings") or AlexaSettingsClient()
        self.user = components.get("user") or User()
        self.search = Search()
        self.browse = components.get("browse") or Browse(deps=self, store=self.user)
        self.listeners = components.get("listeners") or Listener(self.user)
        self.onboarding = components.get("onboarding") or Onboarding(self.user)
        playback_state = components.get("playback_store") or PlaybackState(self.user)
        playback_items = components.get("playback_queue") or PlaybackQueue(self.user)
        self.locality = components.get("locality") or AlexaLocalityService(settings_client)
        self.listener_profile = components.get("listener_profile") or ListenerProfileService(
            settings_client,
            self.listeners,
        )
        self.alexa = components.get("alexa") or AlexaClient()
        self.events = components.get("events") or OutboundEventService(
            producer=SqsEventClient(),
            webhook=WebhookEventClient(),
        )
        self.reminders = components.get("reminders") or AlexaReminderService(self.alexa, self.user)
        self.feedback = components.get("feedback") or FeedbackService(self.reminders, self.events)
        self.playback = components.get("playback") or Playback(
            self.alexa,
            playback_state,
            playback_items,
            self.reminders,
            self.events,
        )
        self.heara = components.get("heara") or HearApiClient()
        self.listener_identity = components.get("listener_identity") or ListenerIdentityService(
            self.heara,
            settings_client,
            enabled=settings.HEAR_CANONICAL_IDENTITY_ENABLED,
            timeout_ms=settings.identity_timeout_ms,
        )
        self.notification_inbox = components.get(
            "notification_inbox"
        ) or NotificationInboxFactory.build(
            settings.HEAR_NOTIFICATION_TABLE,
            region=settings.ddb_region,
        )
        self.proactive_events = components.get("proactive_events") or ProactiveEventsClient(
            client_id=settings.ALEXA_PROACTIVE_CLIENT_ID,
            client_secret=settings.ALEXA_PROACTIVE_CLIENT_SECRET,
            stage=settings.STAGE,
        )
        self.notification_delivery = components.get(
            "notification_delivery"
        ) or NotificationDeliveryService(
            self.notification_inbox,
            self.proactive_events,
        )
        self.listener_sync = components.get("listener_sync") or ListenerSyncService(
            self.heara,
            enabled=settings.HEAR_LISTENER_SYNC_ON_LAUNCH,
        )
        self.reports = components.get("reports") or Report(self.events)
        self.resolver = components.get("resolver") or ResolverClient(
            ResolverOptions(api_key=settings.HEAR_API_KEY)
        )
        self.progressive = components.get("progressive") or ProgressiveResponseClient()
        self.availability = components.get("availability") or Availability(deps=self)
        self.permission = components.get("permission") or Permission(deps=self)
        self.notifications = components.get("notifications") or Notification(deps=self)
        self.error_reporter = components.get("error_reporter") or ErrorReporter()

    def create(self, component_type):
        parameters = inspect.signature(component_type).parameters
        if "deps" in parameters:
            return component_type(deps=self)
        return component_type()
