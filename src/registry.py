from __future__ import annotations

from src.container import ApplicationContainer
from src.controllers.browse import (
    BrowseContentHandler,
    ShowMoreBrowseHandler,
    WhatsTrendingHandler,
)
from src.controllers.can_fulfill import CanFulfillIntentHandler
from src.controllers.confirmation import NoIntentHandler, YesIntentHandler
from src.controllers.error import ErrorHandler
from src.controllers.fallback import FallbackHandler, UnmatchedIntentHandler
from src.controllers.feedback import (
    FeedbackEnjoyedHandler,
    FeedbackNotEnjoyedHandler,
    FeedbackSomewhatHandler,
    SkipFeedbackHandler,
)
from src.controllers.intent_dispatch import IntentDispatchGateHandler
from src.controllers.launch import LaunchRequestHandler, TownCaptureHandler
from src.controllers.permission import PermissionResumeHandler, SetUpAccountHandler
from src.controllers.play import (
    PlayByCreatorHandler,
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
from src.middleware.feedback_gate import FeedbackGateHandler
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
        FeedbackGateHandler,
        OnboardingGateHandler,
        TownCaptureHandler,
        SearchConfirmationGateHandler,
        IntentDispatchGateHandler,
    )
    REQUEST_INTERCEPTORS = (
        LambdaDeadlineInterceptor,
        LoadPersistenceInterceptor,
        DialogValidationInterceptor,
        IdentityInterceptor,
        ResolverInterceptor,
        ConfirmationMiddleware,
    )
    RESPONSE_INTERCEPTORS = (SavePersistenceInterceptor,)
    REQUEST_CONTROLLERS = (
        PermissionResumeHandler,
        LaunchRequestHandler,
        SetUpAccountHandler,
        WhatsTrendingHandler,
        BrowseContentHandler,
        PlayByCreatorHandler,
        PlayByOrganizationHandler,
        PlayContentHandler,
        ShowMoreBrowseHandler,
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
        FeedbackEnjoyedHandler,
        FeedbackSomewhatHandler,
        FeedbackNotEnjoyedHandler,
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
        for handler_type in RouteRegistry.GATE_HANDLERS:
            builder.add_request_handler(container.create(handler_type))
        builder.add_exception_handler(container.create(ErrorHandler))
        for interceptor_type in RouteRegistry.REQUEST_INTERCEPTORS:
            builder.add_global_request_interceptor(container.create(interceptor_type))
        for interceptor_type in RouteRegistry.RESPONSE_INTERCEPTORS:
            builder.add_global_response_interceptor(container.create(interceptor_type))

    @staticmethod
    def register_controllers(builder, deps: ApplicationContainer | None = None) -> None:
        deps = deps or ApplicationContainer()
        for controller_type in RouteRegistry.REQUEST_CONTROLLERS:
            builder.add_request_handler(deps.create(controller_type))
