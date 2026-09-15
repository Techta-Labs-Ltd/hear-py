from __future__ import annotations

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
from src.models.feedback_response import (
    EnjoyedFeedback,
    NotEnjoyedFeedback,
    RatingRequest,
    SkipFeedback,
    SomewhatFeedback,
)
from src.models.play import PlayContent, PlayOrganization
from src.models.playback_events import PlaybackEvents
from src.models.social import CreatorIdentity, FollowCreator, UnfollowCreator
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
        for handler in (
            CanFulfillIntentHandler(container.resolver),
            DialogValidationGateHandler(),
            AvailabilityDialogHandler(container.availability),
            FeedbackSkipGateHandler(deps=container),
            FeedbackGateHandler(deps=container),
            OnboardingGateHandler(deps=container),
            TownCaptureHandler(deps=container),
            SearchConfirmationGateHandler(),
            IntentDispatchGateHandler(deps=container),
        ):
            builder.add_request_handler(handler)
        builder.add_exception_handler(ErrorHandler(deps=container))
        for interceptor in (
            LambdaDeadlineInterceptor(),
            IdentityInterceptor(deps=container),
            LoadPersistenceInterceptor(),
            DialogValidationInterceptor(),
            ResolverInterceptor(deps=container),
            ConfirmationMiddleware(),
        ):
            builder.add_global_request_interceptor(interceptor)
        builder.add_global_response_interceptor(SavePersistenceInterceptor())

    @staticmethod
    def register_controllers(builder, container: ApplicationContainer) -> None:
        for controller in (
            PermissionResumeHandler(container.permission),
            LaunchRequestHandler(deps=container),
            SetUpAccountHandler(container.permission),
            HearNotificationsHandler(container.notifications),
            EnableNotificationsHandler(container.notifications),
            DisableNotificationsHandler(container.notifications),
            WhatsTrendingHandler(container.browse),
            BrowseContentHandler(container.browse),
            PlayByOrganizationHandler(PlayOrganization(deps=container)),
            PlayContentHandler(PlayContent(deps=container)),
            BrowseNavigationHandler(container.browse),
            SetPlaybackSpeedHandler(deps=container),
            IncreaseSpeedHandler(deps=container),
            DecreaseSpeedHandler(deps=container),
            PauseIntentHandler(deps=container),
            ResumeIntentHandler(deps=container),
            NextIntentHandler(deps=container),
            PreviousIntentHandler(deps=container),
            RepeatIntentHandler(deps=container),
            RewindIntentHandler(deps=container),
            FastForwardIntentHandler(deps=container),
            WhoIsCreatorHandler(CreatorIdentity(deps=container)),
            FollowCreatorHandler(FollowCreator(deps=container)),
            UnfollowCreatorHandler(UnfollowCreator(deps=container)),
            ReportContentHandler(deps=container),
            ReportCreatorHandler(deps=container),
            WhatsThisAboutHandler(deps=container),
            PlaybackStartedHandler(
                container.playback, container.user, container.notifications
            ),
            PlaybackProgressReportHandler(container.playback),
            PlaybackNearlyFinishedHandler(container.playback, container.heara),
            PlaybackFinishedHandler(PlaybackEvents(container.playback, container.user)),
            PlaybackStoppedHandler(container.playback),
            PlaybackFailedHandler(container.playback, container.notifications),
            RateContentHandler(RatingRequest(deps=container)),
            FeedbackEnjoyedHandler(EnjoyedFeedback(deps=container)),
            FeedbackSomewhatHandler(SomewhatFeedback(deps=container)),
            FeedbackNotEnjoyedHandler(NotEnjoyedFeedback(deps=container)),
            FeedbackResponseHandler(
                EnjoyedFeedback(deps=container),
                SomewhatFeedback(deps=container),
                NotEnjoyedFeedback(deps=container),
                SkipFeedback(deps=container),
            ),
            SkipFeedbackHandler(SkipFeedback(deps=container)),
            YesIntentHandler(deps=container),
            NoIntentHandler(deps=container),
            NavigateHomeHandler(deps=container),
            UnsupportedIntentHandler(),
            HelpIntentHandler(),
            CancelIntentHandler(deps=container),
            SessionEndedHandler(deps=container),
            FallbackHandler(deps=container),
            UnmatchedIntentHandler(deps=container),
            UnknownRequestHandler(deps=container),
        ):
            builder.add_request_handler(controller)
