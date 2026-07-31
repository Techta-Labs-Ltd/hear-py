"""Ordered request-handler registry."""
from __future__ import annotations

from src.handlers.audio import (
    PlaybackFailedHandler, PlaybackFinishedHandler, PlaybackNearlyFinishedHandler,
    PlaybackProgressReportHandler, PlaybackStartedHandler, PlaybackStoppedHandler,
)
from src.handlers.feedback import (
    FeedbackEnjoyedHandler, FeedbackNotEnjoyedHandler, FeedbackSomewhatHandler,
    SkipFeedbackHandler,
)
from src.handlers.intents import (
    BrowseContentHandler, CancelIntentHandler, ConnectionsResponseHandler,
    DecreaseSpeedHandler, FallbackHandler,
    FastForwardIntentHandler, FollowCreatorHandler,
    HelpIntentHandler, IncreaseSpeedHandler, LaunchRequestHandler,
    NavigateHomeHandler, NextIntentHandler, NoIntentHandler, PauseIntentHandler,
    PlayByCreatorHandler, PlayByOrganizationHandler, PlayContentHandler,
    PreviousIntentHandler, RepeatIntentHandler, ReportContentHandler,
    ReportCreatorHandler, ResumeIntentHandler, RewindIntentHandler,
    SessionEndedHandler, SetPlaybackSpeedHandler, ShowMoreBrowseHandler,
    UnfollowCreatorHandler, UnknownRequestHandler, UnmatchedIntentHandler,
    UnsupportedIntentHandler, WhatsThisAboutHandler, WhatsTrendingHandler,
    WhoIsCreatorHandler, YesIntentHandler,
)
from src.handlers.notifications import (
    DisableNotificationsHandler, EnableNotificationsHandler, HearNotificationsHandler,
)

REQUEST_HANDLERS = (
    LaunchRequestHandler, ConnectionsResponseHandler, WhatsTrendingHandler,
    BrowseContentHandler,
    PlayByCreatorHandler, PlayByOrganizationHandler, PlayContentHandler,
    ShowMoreBrowseHandler, SetPlaybackSpeedHandler, IncreaseSpeedHandler,
    DecreaseSpeedHandler, PauseIntentHandler, ResumeIntentHandler,
    NextIntentHandler, PreviousIntentHandler, RepeatIntentHandler,
    RewindIntentHandler, FastForwardIntentHandler, WhoIsCreatorHandler,
    FollowCreatorHandler, UnfollowCreatorHandler, ReportContentHandler,
    ReportCreatorHandler, WhatsThisAboutHandler, HearNotificationsHandler,
    PlaybackStartedHandler, PlaybackProgressReportHandler,
    PlaybackNearlyFinishedHandler, PlaybackFinishedHandler,
    PlaybackStoppedHandler, PlaybackFailedHandler, FeedbackEnjoyedHandler,
    FeedbackSomewhatHandler, FeedbackNotEnjoyedHandler, SkipFeedbackHandler,
    EnableNotificationsHandler, DisableNotificationsHandler, YesIntentHandler,
    NoIntentHandler, NavigateHomeHandler, UnsupportedIntentHandler,
    HelpIntentHandler, CancelIntentHandler, SessionEndedHandler, FallbackHandler,
    UnmatchedIntentHandler, UnknownRequestHandler,
)


def register_handlers(builder) -> None:
    """Register application handlers in dispatch order."""
    for handler_type in REQUEST_HANDLERS:
        builder.add_request_handler(handler_type())
