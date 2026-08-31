class DialogConstants:
    VALIDATION_FAILURE = "_dialogValidationFailure"
    DIALOG_TTL_SECONDS = 10 * 60
    DIALOG_LEGACY_FLAGS = {
        "search_confirmation": "awaitingSearchConfirmation",
        "feedback": "awaitingFeedback",
        "report_decision": "awaitingReportDecision",
        "resume": "awaitingResume",
    }
    TRANSIENT_DISCOVERY_DIALOGS = frozenset({"search_confirmation", "ambiguity"})
    DEFERRED_DISCOVERY_INTENTS = frozenset(
        {
            "PlayContentIntent",
            "PlayLocalIntent",
            "PlayRecommendationIntent",
            "PlayByOrganizationIntent",
            "PlayByCreatorIntent",
            "PlayPublicationIntent",
            "BrowseContentIntent",
            "WhatsTrendingIntent",
        }
    )
