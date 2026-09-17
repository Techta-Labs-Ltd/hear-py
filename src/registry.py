from __future__ import annotations

from src.alexa.feedback_response import RatingRequest
from src.alexa.playback_events import PlaybackEvents
from src.container import ApplicationContainer
from src.controllers.availability import AvailabilityDialogHandler
from src.controllers.browse import (
    BrowseContentHandler,
    BrowseNavigationHandler,
    WhatsTrendingHandler,
)
from src.controllers.can_fulfill import CanFulfillIntentHandler
from src.controllers.confirmation import NoIntentHandler, YesIntentHandler
from src.controllers.error import ErrorHandler
from src.controllers.fallback import FallbackHandler, UnmatchedIntentHandler
from src.controllers.feedback import (
    FeedbackEnjoyedHandler,
    FeedbackNotEnjoyedHandler,
    FeedbackResponseHandler,
    FeedbackSomewhatHandler,
    RateContentHandler,
    SkipFeedbackHandler,
)
from src.controllers.intent_dispatch import IntentDispatchGateHandler
from src.controllers.launch import LaunchRequestHandler, TownCaptureHandler
from src.controllers.notifications import (
    DisableNotificationsHandler,
    EnableNotificationsHandler,
    HearNotificationsHandler,
)
from src.controllers.permission import PermissionResumeHandler, SetUpAccountHandler
from src.controllers.play import (
    PlayByOrganizationHandler,
    PlayContentHandler,
)
from src.controllers.playback_controls import (
    DecreaseSpeedHandler,
    FastForwardIntentHandler,
    IncreaseSpeedHandler,
    NextIntentHandler,
    PauseIntentHandler,
    PreviousIntentHandler,
    RepeatIntentHandler,
    ResumeIntentHandler,
    RewindIntentHandler,
    SetPlaybackSpeedHandler,
)
from src.controllers.playback_events import (
    PlaybackFailedHandler,
    PlaybackFinishedHandler,
    PlaybackNearlyFinishedHandler,
    PlaybackProgressReportHandler,
    PlaybackStartedHandler,
    PlaybackStoppedHandler,
)
from src.controllers.report import (
    ReportContentHandler,
    ReportCreatorHandler,
    WhatsThisAboutHandler,
)
from src.controllers.social import (
    FollowCreatorHandler,
    UnfollowCreatorHandler,
    WhoIsCreatorHandler,
)
from src.controllers.system import (
    CancelIntentHandler,
    HelpIntentHandler,
    HelpMoreIntentHandler,
    NavigateHomeHandler,
    SessionEndedHandler,
    UnknownRequestHandler,
    UnsupportedIntentHandler,
)
from src.middleware.confirmation import (
    ConfirmationMiddleware,
    SearchConfirmationGateHandler,
)
from src.middleware.deadline import LambdaDeadlineInterceptor
from src.middleware.dialog_validation import (
    DialogValidationGateHandler,
    DialogValidationInterceptor,
)
from src.middleware.direct_intent import DirectIntentPhraseInterceptor
from src.middleware.feedback_gate import FeedbackGateHandler, FeedbackSkipGateHandler
from src.middleware.identity import IdentityInterceptor
from src.middleware.onboarding_gate import OnboardingGateHandler
from src.middleware.persistence import (
    LoadPersistenceInterceptor,
    SavePersistenceInterceptor,
)
from src.middleware.resolver import ResolverInterceptor


class RouteRegistry:
    GATE_HANDLERS = (
        CanFulfillIntentHandler,
        DialogValidationGateHandler,
        AvailabilityDialogHandler,
        FeedbackSkipGateHandler,
        FeedbackGateHandler,
        OnboardingGateHandler,
        TownCaptureHandler,
        SearchConfirmationGateHandler,
        IntentDispatchGateHandler,
    )
    REQUEST_INTERCEPTORS = (
        LambdaDeadlineInterceptor,
        IdentityInterceptor,
        LoadPersistenceInterceptor,
        DialogValidationInterceptor,
        DirectIntentPhraseInterceptor,
        ResolverInterceptor,
        ConfirmationMiddleware,
    )
    RESPONSE_INTERCEPTORS = (SavePersistenceInterceptor,)
    REQUEST_CONTROLLERS = (
        PermissionResumeHandler,
        LaunchRequestHandler,
        SetUpAccountHandler,
        HearNotificationsHandler,
        EnableNotificationsHandler,
        DisableNotificationsHandler,
        WhatsTrendingHandler,
        BrowseContentHandler,
        PlayByOrganizationHandler,
        PlayContentHandler,
        HelpMoreIntentHandler,
        BrowseNavigationHandler,
        SetPlaybackSpeedHandler,
        IncreaseSpeedHandler,
        DecreaseSpeedHandler,
        PauseIntentHandler,
        ResumeIntentHandler,
        NextIntentHandler,
        PreviousIntentHandler,
        RepeatIntentHandler,
        RewindIntentHandler,
        FastForwardIntentHandler,
        WhoIsCreatorHandler,
        FollowCreatorHandler,
        UnfollowCreatorHandler,
        ReportContentHandler,
        ReportCreatorHandler,
        WhatsThisAboutHandler,
        PlaybackStartedHandler,
        PlaybackProgressReportHandler,
        PlaybackNearlyFinishedHandler,
        PlaybackFinishedHandler,
        PlaybackStoppedHandler,
        PlaybackFailedHandler,
        RateContentHandler,
        FeedbackEnjoyedHandler,
        FeedbackSomewhatHandler,
        FeedbackNotEnjoyedHandler,
        FeedbackResponseHandler,
        SkipFeedbackHandler,
        YesIntentHandler,
        NoIntentHandler,
        NavigateHomeHandler,
        UnsupportedIntentHandler,
        HelpIntentHandler,
        CancelIntentHandler,
        SessionEndedHandler,
        FallbackHandler,
        UnmatchedIntentHandler,
        UnknownRequestHandler,
    )

    @staticmethod
    def register(builder, container: ApplicationContainer) -> None:
        RouteRegistry.register_middleware(builder, container)
        RouteRegistry.register_controllers(builder, container)

    @staticmethod
    def register_middleware(builder, container: ApplicationContainer) -> None:
        for factory in (
            lambda _request: CanFulfillIntentHandler(container.resolver),
            lambda _request: DialogValidationGateHandler(),
            lambda request: AvailabilityDialogHandler(
                container.build_request_components(request).availability
            ),
            lambda request: FeedbackSkipGateHandler(
                container.user, container.build_request_skip_feedback(request)
            ),
            lambda _request: FeedbackGateHandler(container.feedback, container.user),
            lambda request: container.build_onboarding_gate(request),
            lambda _request: TownCaptureHandler(
                container.build_town_capture(), container.user
            ),
            lambda _request: SearchConfirmationGateHandler(),
            lambda request: IntentDispatchGateHandler(
                container.build_request_intent_dispatcher(request)
            ),
        ):
            builder.add_request_handler_factory(factory)
        builder.add_exception_handler(ErrorHandler(container.error_reporter))
        for interceptor in (
            LambdaDeadlineInterceptor(),
            IdentityInterceptor(container.listener_identity, container.user),
            LoadPersistenceInterceptor(),
            DialogValidationInterceptor(),
            DirectIntentPhraseInterceptor(),
            container.build_resolver_interceptor(),
            ConfirmationMiddleware(),
        ):
            builder.add_global_request_interceptor(interceptor)
        builder.add_global_response_interceptor(SavePersistenceInterceptor())

    @staticmethod
    def register_controllers(builder, container: ApplicationContainer) -> None:
        for factory in (
            lambda _request: PermissionResumeHandler(container.permission),
            lambda request: LaunchRequestHandler(
                container.build_request_launch_workflow(request), container.playback
            ),
            lambda _request: SetUpAccountHandler(container.permission),
            lambda request: HearNotificationsHandler(
                container.build_request_notifications(request)
            ),
            lambda request: EnableNotificationsHandler(
                container.build_request_notifications(request)
            ),
            lambda request: DisableNotificationsHandler(
                container.build_request_notifications(request)
            ),
            lambda request: WhatsTrendingHandler(
                container.build_request_components(request).browse
            ),
            lambda request: BrowseContentHandler(
                container.build_request_components(request).browse
            ),
            lambda request: PlayByOrganizationHandler(
                container.build_request_play_organization(request)
            ),
            lambda request: PlayContentHandler(container.build_request_play_content(request)),
            lambda _request: HelpMoreIntentHandler(),
            lambda request: BrowseNavigationHandler(
                container.build_request_components(request).browse
            ),
            lambda request: SetPlaybackSpeedHandler(container.build_playback_controls(request)),
            lambda request: IncreaseSpeedHandler(container.build_playback_controls(request)),
            lambda request: DecreaseSpeedHandler(container.build_playback_controls(request)),
            lambda request: PauseIntentHandler(container.build_playback_controls(request)),
            lambda request: ResumeIntentHandler(container.build_playback_controls(request)),
            lambda request: NextIntentHandler(container.build_playback_controls(request)),
            lambda request: PreviousIntentHandler(container.build_playback_controls(request)),
            lambda request: RepeatIntentHandler(container.build_playback_controls(request)),
            lambda request: RewindIntentHandler(container.build_playback_controls(request)),
            lambda request: FastForwardIntentHandler(container.build_playback_controls(request)),
            lambda _request: WhoIsCreatorHandler(container.build_creator_identity()),
            lambda request: FollowCreatorHandler(container.build_request_follow_creator(request)),
            lambda _request: UnfollowCreatorHandler(container.build_unfollow_creator()),
            lambda request: ReportContentHandler(
                container.user,
                container.reports,
                container.feedback,
                container.build_playback_controls(request),
                container.events,
            ),
            lambda _request: ReportCreatorHandler(
                container.user, container.reports, container.feedback, container.events
            ),
            lambda _request: WhatsThisAboutHandler(container.user),
            lambda _request: PlaybackStartedHandler(
                PlaybackEvents(container.playback, container.user),
                container.build_request_notifications(_request),
            ),
            lambda _request: PlaybackProgressReportHandler(
                PlaybackEvents(container.playback, container.user)
            ),
            lambda request: PlaybackNearlyFinishedHandler(
                PlaybackEvents(container.playback, container.user),
                container.playback,
                container.bind_hear_client(request),
            ),
            lambda _request: PlaybackFinishedHandler(
                PlaybackEvents(container.playback, container.user)
            ),
            lambda _request: PlaybackStoppedHandler(
                PlaybackEvents(container.playback, container.user)
            ),
            lambda _request: PlaybackFailedHandler(
                PlaybackEvents(container.playback, container.user),
                container.build_request_notifications(_request),
            ),
            lambda request: RateContentHandler(
                RatingRequest(
                    container.feedback,
                    container.build_playback_controls(request),
                    container.user,
                )
            ),
            lambda request: FeedbackEnjoyedHandler(
                container.build_request_enjoyed_feedback(request)
            ),
            lambda request: FeedbackSomewhatHandler(
                container.build_request_somewhat_feedback(request)
            ),
            lambda request: FeedbackNotEnjoyedHandler(
                container.build_request_not_enjoyed_feedback(request)
            ),
            lambda request: FeedbackResponseHandler(
                container.build_request_enjoyed_feedback(request),
                container.build_request_somewhat_feedback(request),
                container.build_request_not_enjoyed_feedback(request),
                container.build_request_skip_feedback(request),
            ),
            lambda request: SkipFeedbackHandler(container.build_request_skip_feedback(request)),
            lambda request: YesIntentHandler(container.build_request_affirmative(request)),
            lambda request: NoIntentHandler(container.build_request_decline(request)),
            lambda request: NavigateHomeHandler(
                container.build_request_components(request).browse
            ),
            lambda _request: UnsupportedIntentHandler(),
            lambda _request: HelpIntentHandler(),
            lambda _request: CancelIntentHandler(container.user, container.playback),
            lambda _request: SessionEndedHandler(container.playback),
            lambda _request: FallbackHandler(container.user, container.onboarding),
            lambda _request: UnmatchedIntentHandler(container.user, container.onboarding),
            lambda _request: UnknownRequestHandler(container.user, container.onboarding),
        ):
            builder.add_request_handler_factory(factory)
