from __future__ import annotations


class DirectIntentPolicy:
    BYPASS_RESOLVER_INTENTS = frozenset(
        {
            "WhatsTrendingIntent",
            "PlayRecommendationIntent",
            "SetUpAccountIntent",
            "SetPlaybackSpeedIntent",
            "IncreaseSpeedIntent",
            "DecreaseSpeedIntent",
            "RewindIntent",
            "FastForwardIntent",
            "RateContentIntent",
            "FeedbackEnjoyedIntent",
            "FeedbackSomewhatIntent",
            "FeedbackNotEnjoyedIntent",
            "FeedbackResponseIntent",
            "SkipFeedbackIntent",
            "HearNotificationsIntent",
            "EnableNotificationsIntent",
            "DisableNotificationsIntent",
            "ReportContentIntent",
            "ReportCreatorIntent",
            "WhatsThisAboutIntent",
            "WhoIsCreatorIntent",
            "FollowCreatorIntent",
            "UnfollowCreatorIntent",
            "ShowMoreBrowseIntent",
            "ShowPreviousBrowseIntent",
            "NavigateHomeIntent",
            "AMAZON.YesIntent",
            "AMAZON.NoIntent",
            "AMAZON.CancelIntent",
            "AMAZON.StopIntent",
            "AMAZON.HelpIntent",
            "AMAZON.PauseIntent",
            "AMAZON.ResumeIntent",
            "AMAZON.NextIntent",
            "AMAZON.PreviousIntent",
            "AMAZON.RepeatIntent",
            "AMAZON.StartOverIntent",
        }
    )

    PHRASE_ROUTABLE_SEARCH_INTENTS = frozenset(
        {
            "OpenDiscoveryIntent",
            "CarrierlessDiscoveryIntent",
            "PlayContentIntent",
            "PlayLatestContentIntent",
            "SearchContentIntent",
            "SearchCreatorIntent",
            "SearchOrganizationIntent",
            "SearchPublicationIntent",
            "PlayByOrganizationIntent",
            "PlayPublicationIntent",
            "SelectOrganizationIntent",
            "SelectPublicationSourceIntent",
            "BrowseContentIntent",
            "BrowseByCategoryIntent",
        }
    )
