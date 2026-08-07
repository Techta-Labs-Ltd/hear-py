from __future__ import annotations
from src.dependencies import Dependencies
from src.handlers.audio import (
    PlaybackFailedHandler,
    PlaybackFinishedHandler,
    PlaybackNearlyFinishedHandler,
    PlaybackProgressReportHandler,
    PlaybackStartedHandler,
    PlaybackStoppedHandler,
)
from src.handlers.feedback import (
    FeedbackEnjoyedHandler,
    FeedbackNotEnjoyedHandler,
    FeedbackSomewhatHandler,
    SkipFeedbackHandler,
)
from src.handlers.browse import (
    BrowseContentHandler,
    ShowMoreBrowseHandler,
    WhatsTrendingHandler,
)
from src.handlers.fallback import FallbackHandler, UnmatchedIntentHandler
from src.handlers.launch import LaunchRequestHandler
from src.handlers.onboarding import ConnectionsResponseHandler
from src.handlers.play import (
    PlayByCreatorHandler,
    PlayByOrganizationHandler,
    PlayContentHandler,
)
from src.handlers.playback import (
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
from src.handlers.report import (
    ReportContentHandler,
    ReportCreatorHandler,
    WhatsThisAboutHandler,
)
from src.handlers.social import (
    FollowCreatorHandler,
    UnfollowCreatorHandler,
    WhoIsCreatorHandler,
)
from src.handlers.system import (
    CancelIntentHandler,
    HelpIntentHandler,
    NavigateHomeHandler,
    SessionEndedHandler,
    UnknownRequestHandler,
    UnsupportedIntentHandler,
)
from src.handlers.yesno import NoIntentHandler, YesIntentHandler
REQUEST_HANDLERS = (
    LaunchRequestHandler, ConnectionsResponseHandler, WhatsTrendingHandler,
    BrowseContentHandler,
    PlayByCreatorHandler, PlayByOrganizationHandler, PlayContentHandler,
    ShowMoreBrowseHandler, SetPlaybackSpeedHandler, IncreaseSpeedHandler,
    DecreaseSpeedHandler, PauseIntentHandler, ResumeIntentHandler,
    NextIntentHandler, PreviousIntentHandler, RepeatIntentHandler,
    RewindIntentHandler, FastForwardIntentHandler, WhoIsCreatorHandler,
    FollowCreatorHandler, UnfollowCreatorHandler, ReportContentHandler,
    ReportCreatorHandler, WhatsThisAboutHandler,
    PlaybackStartedHandler, PlaybackProgressReportHandler,
    PlaybackNearlyFinishedHandler, PlaybackFinishedHandler,
    PlaybackStoppedHandler, PlaybackFailedHandler, FeedbackEnjoyedHandler,
    FeedbackSomewhatHandler, FeedbackNotEnjoyedHandler, SkipFeedbackHandler,
    YesIntentHandler, NoIntentHandler, NavigateHomeHandler, UnsupportedIntentHandler,
    HelpIntentHandler, CancelIntentHandler, SessionEndedHandler, FallbackHandler,
    UnmatchedIntentHandler, UnknownRequestHandler,
)


def register_handlers(builder, deps: Dependencies | None = None) -> None:
    """Register application handlers in dispatch order."""
    if deps is None:
        deps = Dependencies()
    for handler_type in REQUEST_HANDLERS:
        try:
            builder.add_request_handler(handler_type(deps=deps))
        except TypeError:
            builder.add_request_handler(handler_type())
