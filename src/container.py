from __future__ import annotations

from config import settings
from src.clients.alexa import AlexaClient
from src.clients.alexa_settings import AlexaSettingsClient
from src.clients.events import SqsEventClient, WebhookEventClient
from src.clients.hear import HearApiClient
from src.clients.notifications import NotificationApiClient
from src.clients.proactive import ProactiveEventsClient
from src.clients.progressive import ProgressiveResponseClient
from src.clients.resolver import ResolverClient, ResolverOptions
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
from src.services.events import OutboundEventService
from src.services.listener_identity import ListenerIdentityService
from src.services.listener_sync import ListenerSyncService
from src.services.notification_delivery import NotificationDeliveryService
from src.services.observability import ErrorReporter


class ApplicationContainer:
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
        "notification_api",
        "proactive_events",
        "notification_delivery",
        "notifications",
    )

    def __init__(
        self,
        *,
        locality: AlexaLocalityService | None = None,
        listener_profile: ListenerProfileService | None = None,
        listener_sync: ListenerSyncService | None = None,
        listener_identity: ListenerIdentityService | None = None,
        events: OutboundEventService | None = None,
        feedback: FeedbackService | None = None,
        browse: Browse | None = None,
        availability: Availability | None = None,
        playback: Playback | None = None,
        search: Search | None = None,
        user: User | None = None,
        listeners: Listener | None = None,
        onboarding: Onboarding | None = None,
        reports: Report | None = None,
        playback_store: PlaybackState | None = None,
        playback_queue: PlaybackQueue | None = None,
        alexa_settings: AlexaSettingsClient | None = None,
        alexa: AlexaClient | None = None,
        heara: HearApiClient | None = None,
        resolver: ResolverClient | None = None,
        progressive: ProgressiveResponseClient | None = None,
        permission: Permission | None = None,
        notification_api: NotificationApiClient | None = None,
        proactive_events: ProactiveEventsClient | None = None,
        notification_delivery: NotificationDeliveryService | None = None,
        notifications: Notification | None = None,
        error_reporter: ErrorReporter | None = None,
    ) -> None:
        settings_client = alexa_settings or AlexaSettingsClient()
        self.user = user or User()
        self.search = search or Search()
        self.browse = browse or Browse(deps=self, store=self.user)
        self.listeners = listeners or Listener(self.user)
        self.onboarding = onboarding or Onboarding(self.user)
        playback_state = playback_store or PlaybackState(self.user)
        playback_items = playback_queue or PlaybackQueue(self.user)
        self.locality = locality or AlexaLocalityService(settings_client)
        self.listener_profile = listener_profile or ListenerProfileService(
            settings_client,
            self.listeners,
        )
        self.alexa = alexa or AlexaClient()
        self.events = events or OutboundEventService(
            producer=SqsEventClient(),
            webhook=WebhookEventClient(),
        )
        self.feedback = feedback or FeedbackService(events=self.events)
        self.playback = playback or Playback(
            self.alexa,
            playback_state,
            playback_items,
            self.events,
        )
        self.heara = heara or HearApiClient()
        self.notification_api = notification_api or NotificationApiClient()
        self.listener_identity = listener_identity or ListenerIdentityService(
            self.heara,
            settings_client,
            enabled=settings.HEAR_CANONICAL_IDENTITY_ENABLED,
            timeout_ms=settings.identity_timeout_ms,
        )
        self.proactive_events = proactive_events or ProactiveEventsClient(
            client_id=settings.ALEXA_PROACTIVE_CLIENT_ID,
            client_secret=settings.ALEXA_PROACTIVE_CLIENT_SECRET,
            stage=settings.STAGE,
        )
        self.notification_delivery = notification_delivery or NotificationDeliveryService(
            self.notification_api,
            self.proactive_events,
        )
        self.listener_sync = listener_sync or ListenerSyncService(
            self.heara,
            enabled=settings.HEAR_LISTENER_SYNC_ON_LAUNCH,
        )
        self.reports = reports or Report(self.events)
        self.resolver = resolver or ResolverClient(
            ResolverOptions(api_key=settings.HEAR_API_KEY)
        )
        self.progressive = progressive or ProgressiveResponseClient()
        self.availability = availability or Availability(deps=self)
        self.notifications = notifications or Notification(deps=self)
        self.permission = permission or Permission(
            self.user,
            self.onboarding,
            self.listener_profile,
            self.listener_sync,
            self.notifications,
            self.progressive,
            self.locality,
            self.resolver,
        )
        self.error_reporter = error_reporter or ErrorReporter()
