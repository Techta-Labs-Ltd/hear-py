from __future__ import annotations

import inspect

from config import settings
from src.clients.alexa import AlexaClient
from src.clients.alexa_settings import AlexaSettingsClient
from src.clients.events import SqsEventClient, WebhookEventClient
from src.clients.hear import HearApiClient
from src.clients.progressive import ProgressiveResponseClient
from src.clients.resolver import ResolverClient, ResolverOptions
from src.models.browse import Browse
from src.models.feedback import FeedbackService
from src.models.listener import Listener
from src.models.onboarding import Onboarding
from src.models.playback import Playback
from src.models.playback_state import PlaybackQueue, PlaybackState
from src.models.report import Report
from src.models.search import Search
from src.models.user import User
from src.services.alexa_locality import AlexaLocalityService
from src.services.alexa_profile import ListenerProfileService
from src.services.alexa_reminder import AlexaReminderService
from src.services.events import OutboundEventService
from src.services.listener_sync import ListenerSyncService
from src.services.observability import ErrorReporter


class ApplicationContainer:
    COMPONENT_NAMES = frozenset(
        {
            "locality",
            "listener_profile",
            "listener_sync",
            "events",
            "feedback",
            "browse",
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
            "error_reporter",
        }
    )
    __slots__ = (
        "locality",
        "listener_profile",
        "listener_sync",
        "events",
        "feedback",
        "browse",
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
        self.listener_sync = components.get("listener_sync") or ListenerSyncService(
            self.heara,
            enabled=settings.HEAR_LISTENER_SYNC_ON_LAUNCH,
        )
        self.reports = components.get("reports") or Report(self.events)
        self.resolver = components.get("resolver") or ResolverClient(
            ResolverOptions(api_key=settings.HEAR_API_KEY)
        )
        self.progressive = components.get("progressive") or ProgressiveResponseClient()
        self.error_reporter = components.get("error_reporter") or ErrorReporter()

    def create(self, component_type):
        parameters = inspect.signature(component_type).parameters
        if "deps" in parameters:
            return component_type(deps=self)
        return component_type()
