class DialogConstants:
    VALIDATION_FAILURE = "_dialogValidationFailure"
    DIALOG_TTL_SECONDS = 10 * 60
    CHOICE_DISMISS_INTENTS = frozenset({"DismissChoicesIntent"})
    DIALOG_LEGACY_FLAGS = {
        "search_confirmation": "awaitingSearchConfirmation",
        "feedback": "awaitingFeedback",
        "report_decision": "awaitingReportDecision",
        "resume": "awaitingResume",
        "notification": "awaitingNotificationChoice",
        "organization_name": "awaitingOrganizationName",
        "publication_source": "awaitingPublicationSource",
        "feedback_continuation": "awaitingFeedbackContinuation",
    }
    SLOT_CAPTURE = {
        "creator_location": {
            "intentName": "SelectCreatorCityIntent",
            "slotName": "cityQuery",
        },
        "organization_name": {
            "intentName": "SelectOrganizationIntent",
            "slotName": "organizationQuery",
        },
        "publication_source": {
            "intentName": "SelectPublicationSourceIntent",
            "slotName": "publicationSourceQuery",
        },
    }
    TRANSIENT_DISCOVERY_DIALOGS = frozenset(
        {
            "search_confirmation",
            "ambiguity",
            "availability",
            "asr_repair",
            "organization_name",
            "creator_location",
            "publication_source",
        }
    )
    DEFERRED_DISCOVERY_INTENTS = frozenset(
        {
            "OpenDiscoveryIntent",
            "PlayContentIntent",
            "PlayLocalIntent",
            "PlayRecommendationIntent",
            "PlayByOrganizationIntent",
            "SelectOrganizationIntent",
            "SelectCreatorCityIntent",
            "SelectPublicationSourceIntent",
            "PlayPublicationIntent",
            "BrowseContentIntent",
            "WhatsTrendingIntent",
        }
    )
