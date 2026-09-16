from __future__ import annotations

from dataclasses import dataclass

from config import settings
from src.alexa.affirmative import Affirmative
from src.alexa.availability import Availability
from src.alexa.browse import Browse
from src.alexa.context import RequestContext
from src.alexa.decline import Decline
from src.alexa.feedback_response import (
    EnjoyedFeedback,
    NotEnjoyedFeedback,
    SkipFeedback,
    SomewhatFeedback,
)
from src.alexa.feedback_service import FeedbackService
from src.alexa.intent_dispatch import IntentDispatcher
from src.alexa.launch import LaunchWorkflow
from src.alexa.notifications import AlexaNotificationAdapter
from src.alexa.onboarding import Onboarding, SetLocation, TownCapture
from src.alexa.permission import Permission
from src.alexa.play import PlayContent, PlayCreator, PlayOrganization
from src.alexa.playback_controls import PlaybackControls
from src.alexa.playback_state import PlaybackQueue, PlaybackState
from src.alexa.playback_workflow import Playback
from src.alexa.search import Search
from src.alexa.social import CreatorIdentity, FollowCreator, UnfollowCreator
from src.alexa.suggestion import SuggestionConfirmation
from src.clients.alexa import AlexaClient
from src.clients.alexa_settings import AlexaSettingsClient
from src.clients.events import SqsEventClient, WebhookEventClient
from src.clients.hear import HearApiClient, HearRequestIdentity, ListenerBoundHearClient
from src.clients.notifications import NotificationApiClient
from src.clients.proactive import ProactiveEventsClient
from src.clients.progressive import ProgressiveResponseClient
from src.clients.resolver import ResolverClient, ResolverOptions
from src.middleware.onboarding_gate import OnboardingGateHandler
from src.middleware.resolver import ResolverInterceptor
from src.models.notifications import Notification
from src.models.report import Report
from src.models.user import User
from src.services.alexa_locality import AlexaLocalityService
from src.services.alexa_profile import ListenerProfileService
from src.services.events import OutboundEventService
from src.services.listener_identity import ListenerIdentityService
from src.services.listener_repository import Listener
from src.services.listener_sync import ListenerSyncService
from src.services.notification_delivery import NotificationDeliveryService
from src.services.observability import ErrorReporter


@dataclass(frozen=True, slots=True)
class RequestComponents:
    browse: Browse
    availability: Availability


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
        "playback_controls",
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
        "notification_workflow",
        "notifications",
        "request_availability",
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
        request_availability: Availability | None = None,
        playback: Playback | None = None,
        playback_controls: PlaybackControls | None = None,
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
        notifications: AlexaNotificationAdapter | None = None,
        error_reporter: ErrorReporter | None = None,
    ) -> None:
        settings_client = alexa_settings or AlexaSettingsClient()
        self.user = user or User()
        self.search = search or Search()
        self.request_availability = request_availability
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
            stage_event=User.stage_outbox_event if settings.HEAR_OUTBOX_ENABLED else None,
        )
        self.feedback = feedback or FeedbackService(events=self.events)
        self.playback = playback or Playback(
            self.alexa,
            playback_state,
            playback_items,
            self.events,
        )
        self.heara = heara or HearApiClient()
        self.playback_controls = playback_controls or PlaybackControls(
            self.playback,
            self.user,
            self.heara,
        )
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
        self.reports = reports or Report()
        self.resolver = resolver or ResolverClient(
            ResolverOptions(api_key=settings.HEAR_API_KEY)
        )
        self.progressive = progressive or ProgressiveResponseClient()

        async def begin_recommendations(handler_input, *, nlp=None):
            return await self.availability.begin_recommendations(
                handler_input,
                nlp=nlp,
            )

        self.browse = browse or Browse(
            self.user,
            self.heara,
            self.progressive,
            self.playback,
            begin_recommendations,
        )
        self.availability = availability or Availability(
            self.heara,
            self.progressive,
            self.user,
            self.browse,
            self.playback,
        )
        def enable_notifications_after_permission(handler_input):
            return self.notifications.enable_after_permission(handler_input)

        self.permission = permission or Permission(
            self.user,
            self.onboarding,
            self.listener_profile,
            self.listener_sync,
            enable_notifications_after_permission,
            self.progressive,
            self.locality,
            self.resolver,
        )
        self.notification_workflow = Notification(
            self.notification_api,
            self.heara,
        )
        self.notifications = notifications or AlexaNotificationAdapter(
            self.notification_workflow,
            self.user,
            self.progressive,
            self.browse,
            self.playback,
            self.permission,
            self.events,
            notification_api_enabled=bool(getattr(self.notification_api, "enabled", True)),
        )
        self.error_reporter = error_reporter or ErrorReporter()

    def bind_hear_client(self, handler_input) -> ListenerBoundHearClient:
        """Create an immutable request identity view over the shared Hear client."""
        request = RequestContext.bind(handler_input)
        store = self.user.snapshot(handler_input)
        return self.heara.bind(
            HearRequestIdentity(
                alexa_user_id=request.alexa_user_id,
                listener_id=store.get("listenerId"),
            )
        )

    def build_playback_controls(self, handler_input) -> PlaybackControls:
        return PlaybackControls(
            self.playback,
            self.user,
            self.bind_hear_client(handler_input),
        )

    def build_request_components(self, handler_input) -> RequestComponents:
        """Build the listener-bound discovery graph for one request only."""
        heara = self.bind_hear_client(handler_input)
        availability: Availability | None = None

        async def begin_recommendations(request, *, nlp=None):
            if availability is None:
                raise RuntimeError("request discovery graph is incomplete")
            return await availability.begin_recommendations(request, nlp=nlp)

        browse = Browse(
            self.user,
            heara,
            self.progressive,
            self.playback,
            begin_recommendations,
        )
        availability = self.request_availability or Availability(
            heara,
            self.progressive,
            self.user,
            browse,
            self.playback,
        )
        return RequestComponents(browse=browse, availability=availability)

    def build_request_notifications(
        self, handler_input, components: RequestComponents | None = None
    ) -> AlexaNotificationAdapter:
        discovery = components or self.build_request_components(handler_input)
        workflow = Notification(
            self.notification_api,
            self.bind_hear_client(handler_input),
        )
        return AlexaNotificationAdapter(
            workflow,
            self.user,
            self.progressive,
            discovery.browse,
            self.playback,
            self.permission,
            self.events,
            notification_api_enabled=bool(getattr(self.notification_api, "enabled", True)),
        )

    def build_request_intent_dispatcher(self, handler_input):
        components = self.build_request_components(handler_input)
        play_content = self.build_request_play_content(handler_input, components)
        return IntentDispatcher(
            components.browse,
            components.availability,
            self.user,
            {
                "creator": self.build_request_play_creator(handler_input, components),
                "organization": self.build_request_play_organization(handler_input, components),
                "publication": play_content,
                "category": play_content,
                "following": play_content,
                "general": play_content,
                "search": play_content,
                "town_capture": self.build_town_capture(),
                "location_set": self.build_set_location(),
                "feedback_enjoyed": self.build_request_enjoyed_feedback(handler_input),
                "feedback_not_enjoyed": self.build_request_not_enjoyed_feedback(handler_input),
                "feedback_somewhat": self.build_request_somewhat_feedback(handler_input),
                "feedback_skip": self.build_request_skip_feedback(handler_input),
            },
        )

    def build_resolver_interceptor(self):
        return ResolverInterceptor(self.progressive, self.resolver, self.user)

    async def auto_play_from_search(self, handler_input, search_result, options=None):
        """Execute the shared search-to-playback boundary with explicit collaborators."""
        return await Search.auto_play_first_from_search(
            handler_input,
            search_result,
            options,
            user=self.user,
            browse=self.browse,
            playback=self.playback,
        )

    async def play_first_search_result(self, handler_input, search_result, label=None):
        return await Search._play_first_search_result(
            handler_input,
            search_result,
            label,
            user=self.user,
            browse=self.browse,
            playback=self.playback,
        )

    async def play_followed_creators(self, handler_input):
        return await Search.play_from_followed_creators(
            handler_input,
            user=self.user,
            heara=self.heara,
            progressive=self.progressive,
            browse=self.browse,
            playback=self.playback,
        )

    def build_request_play_content(
        self, handler_input, components: RequestComponents | None = None
    ):
        heara = self.bind_hear_client(handler_input)
        discovery = components or self.build_request_components(handler_input)

        async def play_followed_creators(request):
            return await Search.play_from_followed_creators(
                request,
                user=self.user,
                heara=heara,
                progressive=self.progressive,
                browse=discovery.browse,
                playback=self.playback,
            )

        return PlayContent(
            self.user,
            heara,
            self.progressive,
            discovery.browse,
            self.playback,
            play_followed_creators,
            discovery.browse.more,
        )

    def build_request_play_creator(
        self, handler_input, components: RequestComponents | None = None
    ):
        discovery = components or self.build_request_components(handler_input)

        def ask_creator_city(request):
            return discovery.availability.ask_creator_city(request)

        return PlayCreator(
            self.user,
            self.bind_hear_client(handler_input),
            self.progressive,
            discovery.browse,
            self.playback,
            ask_creator_city,
        )

    def ask_creator_city(self, handler_input):
        return self.availability.ask_creator_city(handler_input)

    def build_request_play_organization(
        self, handler_input, components: RequestComponents | None = None
    ):
        discovery = components or self.build_request_components(handler_input)

        return PlayOrganization(
            self.user,
            self.bind_hear_client(handler_input),
            self.progressive,
            discovery.browse.more,
        )

    def build_creator_identity(self):
        return CreatorIdentity(self.user)

    def build_unfollow_creator(self):
        return UnfollowCreator(self.user, self.events)

    def build_request_follow_creator(self, handler_input):
        components = self.build_request_components(handler_input)
        heara = self.bind_hear_client(handler_input)
        async def play_followed_creators(request):
            return await Search.play_from_followed_creators(
                request,
                user=self.user,
                heara=heara,
                progressive=self.progressive,
                browse=components.browse,
                playback=self.playback,
            )
        return FollowCreator(
            self.user,
            self.feedback,
            self.events,
            play_followed_creators,
        )

    def build_request_enjoyed_feedback(self, handler_input):
        return EnjoyedFeedback(
            self.feedback, self.build_playback_controls(handler_input), self.user
        )

    def build_request_somewhat_feedback(self, handler_input):
        return SomewhatFeedback(
            self.feedback, self.build_playback_controls(handler_input), self.user
        )

    def build_request_not_enjoyed_feedback(self, handler_input):
        del handler_input
        return NotEnjoyedFeedback(self.feedback, self.user)

    def build_request_skip_feedback(self, handler_input):
        return SkipFeedback(
            self.feedback, self.build_playback_controls(handler_input), self.user
        )

    def build_onboarding_gate(self, handler_input):
        async def auto_detect_location(handler_input, store):
            return await self.auto_detect_location_or_manual(handler_input, store)

        def finalize_town_skipped(handler_input, store):
            return self.finalize_town_skipped(handler_input, store)

        def handle_permission_no(handler_input, store):
            return self.handle_permission_no(handler_input, store)

        return OnboardingGateHandler(
            user=self.user,
            onboarding=self.onboarding,
            permission=self.permission,
            town_capture=self.build_town_capture(),
            decline=self.build_request_decline(handler_input),
            auto_detect_location=auto_detect_location,
            finalize_town_skipped=finalize_town_skipped,
            handle_permission_no=handle_permission_no,
        )

    async def stage_town_confirmation(self, handler_input, store, town):
        return await Onboarding.stage_town_confirmation(
            handler_input,
            store,
            town,
            self.onboarding,
            self.progressive,
            self.resolver,
            self.finalize_town_skipped,
        )

    def finalize_town_skipped(self, handler_input, store):
        return Onboarding.finalize_town_skipped(
            handler_input,
            store,
            self.onboarding,
            self.user,
        )

    def handle_permission_no(self, handler_input, store):
        return Onboarding.handle_permission_no(handler_input, store, self.onboarding)

    def handle_permission_yes(self, handler_input, store):
        return Onboarding.handle_permission_yes(handler_input, store, self.onboarding)

    def ask_for_location_permission(self, handler_input, store):
        return Onboarding.ask_for_permission(handler_input, store, self.onboarding)

    def handle_location_not_found(self, handler_input, store):
        return Onboarding.handle_location_not_found(handler_input, store, self.onboarding)

    async def auto_detect_location_or_manual(
        self, handler_input, store, *, after_consent: bool = False
    ):
        return await Onboarding.auto_detect_location_or_manual(
            handler_input,
            store,
            self.onboarding,
            self.progressive,
            self.locality,
            self.resolver,
            self.ask_for_location_permission,
            self.permission.location_fallback,
            self.handle_location_not_found,
            after_consent=after_consent,
        )

    async def finalize_town_captured(self, handler_input, store, phrase):
        return await Onboarding.finalize_town_captured(
            handler_input,
            store,
            phrase,
            self.onboarding,
            self.user,
            self.resolver,
            self.stage_town_confirmation,
        )

    def build_town_capture(self):
        return TownCapture(
            self.user,
            self.onboarding,
            self.finalize_town_skipped,
            self.stage_town_confirmation,
        )

    def build_set_location(self):
        return SetLocation(self.user, self.onboarding, self.stage_town_confirmation)

    def build_request_launch_workflow(self, handler_input):
        def start_town_capture(handler_input, store, user_name):
            return Onboarding.start_town_capture(
                handler_input, store, user_name, self.onboarding
            )

        return LaunchWorkflow(
            user=self.user,
            notifications=self.build_request_notifications(handler_input),
            playback=self.playback,
            listener_profile=self.listener_profile,
            listener_sync=self.listener_sync,
            start_town_capture=start_town_capture,
        )

    def build_request_affirmative(self, handler_input):
        components = self.build_request_components(handler_input)
        play_content = self.build_request_play_content(handler_input, components)

        async def auto_play_from_search(request, search_result, options=None):
            return await Search.auto_play_first_from_search(
                request,
                search_result,
                options,
                user=self.user,
                browse=components.browse,
                playback=self.playback,
            )

        return Affirmative(
            user=self.user,
            notifications=self.build_request_notifications(handler_input, components),
            playback_controls=self.build_playback_controls(handler_input),
            permission=self.permission,
            onboarding=self.onboarding,
            progressive=self.progressive,
            heara=self.bind_hear_client(handler_input),
            availability=components.availability,
            feedback=self.feedback,
            playback=self.playback,
            enjoyed_feedback=self.build_request_enjoyed_feedback(handler_input),
            follow_creator=self.build_request_follow_creator(handler_input),
            suggestion_confirmation=SuggestionConfirmation(
                user=self.user,
                browse=components.browse,
                play_content=play_content,
                play_creator=self.build_request_play_creator(handler_input, components),
                play_organization=self.build_request_play_organization(
                    handler_input, components
                ),
                enjoyed_feedback=self.build_request_enjoyed_feedback(handler_input),
                not_enjoyed_feedback=self.build_request_not_enjoyed_feedback(handler_input),
            ),
            auto_play_from_search=auto_play_from_search,
        )

    def build_request_decline(self, handler_input):
        return Decline(
            user=self.user,
            notifications=self.build_request_notifications(handler_input),
            onboarding=self.onboarding,
            feedback=self.feedback,
            listener_sync=self.listener_sync,
            playback=self.playback,
            playback_controls=self.build_playback_controls(handler_input),
            skip_feedback=self.build_request_skip_feedback(handler_input),
            not_enjoyed_feedback=self.build_request_not_enjoyed_feedback(handler_input),
        )
